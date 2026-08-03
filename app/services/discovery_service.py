import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.domain.discovery.models import CategoryAttemptResult, HydrationResult, PublicStageError
from app.domain.discovery.query_builder import build_queries_for_category, schedule_queries_round_robin
from app.domain.discovery.scoring import score_and_classify_candidate
from app.domain.discovery.selection import select_batch_diverse
from app.integrations.youtube.gateway import YouTubeGateway, YouTubeQuotaError
from app.repositories.discovery_repository import DiscoveryRepository
from app.services.exploration_topic_service import ExplorationTopicService
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


def _is_timeout_error(exc: Exception) -> bool:
    """Retorna True si la excepción representa un timeout de red o de API."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return "timeout" in name or "timeout" in msg


class DiscoveryService:
    def __init__(self, gateway=None):
        self.gateway = gateway or YouTubeGateway()

    def _prepare_snapshots_and_queries(
        self, db, category_ids: List[int], category_budget: int, signal_window: int
    ) -> Tuple[Dict[int, Any], Dict[int, List[Dict[str, Any]]]]:
        """Crea propuestas automáticas y obtiene señales y consultas por categoría."""
        category_signals = {}
        category_queries = {}
        for cat_id in category_ids:
            try:
                ExplorationTopicService.generate_automatic_proposals(db, cat_id)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.warning("Error generando propuestas de temas para categoría %s: %s", cat_id, type(e).__name__)

            signals = DiscoveryRepository.get_category_signals(db, cat_id, signal_window_days=signal_window)
            category_signals[cat_id] = signals
            category_queries[cat_id] = build_queries_for_category(signals, max_queries=category_budget)

        db.commit()
        return category_signals, category_queries

    def _execute_searches(
        self,
        access_token: str,
        scheduled_tasks: List[Tuple[int, Dict[str, Any]]],
        published_after: str,
        results_per_search: int,
        region_code: str,
        relevance_language: str,
        category_ids: List[int],
        heartbeat_callback=None,
    ) -> Tuple[
        int,
        bool,
        Dict[int, Dict[str, Any]],
        Dict[int, bool],
        Dict[int, Optional[PublicStageError]],
        Dict[int, int],
        Dict[int, int],
    ]:
        """Ejecuta las búsquedas programadas en round-robin realizando seguimiento explícito."""
        searches_executed = 0
        quota_exhausted = False
        raw_items_by_cat: Dict[int, Dict[str, Any]] = {cat_id: {} for cat_id in category_ids}
        cat_aborted = {cat_id: False for cat_id in category_ids}
        cat_abort_error: Dict[int, Optional[PublicStageError]] = {cat_id: None for cat_id in category_ids}

        scheduled_counts = {cat_id: 0 for cat_id in category_ids}
        for cat_id, _ in scheduled_tasks:
            scheduled_counts[cat_id] += 1

        completed_counts = {cat_id: 0 for cat_id in category_ids}

        for cat_id, q_task in scheduled_tasks:
            if heartbeat_callback:
                heartbeat_callback()

            if cat_aborted[cat_id]:
                continue

            if quota_exhausted:
                cat_aborted[cat_id] = True
                cat_abort_error[cat_id] = PublicStageError(
                    stage="discovery",
                    code="YOUTUBE_QUOTA_EXHAUSTED",
                    message="Se agotó la cuota de la API de YouTube. Se conservó el lote anterior.",
                    category_id=cat_id,
                )
                continue

            q_str = q_task["q"]
            logger.info("Ejecutando búsqueda para categoría %s", cat_id)

            try:
                items = self.gateway.search_videos(
                    access_token,
                    q=q_str,
                    published_after=published_after,
                    limit=results_per_search,
                    region_code=region_code,
                    relevance_language=relevance_language,
                )
                searches_executed += 1
                completed_counts[cat_id] += 1
                for item in items:
                    v_id = item["youtube_video_id"]
                    raw_items_by_cat[cat_id][v_id] = item
            except YouTubeQuotaError:
                logger.error("Cuota de YouTube agotada en categoría %s", cat_id)
                quota_exhausted = True
                cat_aborted[cat_id] = True
                cat_abort_error[cat_id] = PublicStageError(
                    stage="discovery",
                    code="YOUTUBE_QUOTA_EXHAUSTED",
                    message="Se agotó la cuota de la API de YouTube. Se conservó el lote anterior.",
                    category_id=cat_id,
                )
            except Exception as e:
                err_code = "YOUTUBE_TIMEOUT" if _is_timeout_error(e) else "EXTERNAL_ERROR"
                err_msg = (
                    "YouTube no respondió a tiempo. Se conservó el lote anterior."
                    if _is_timeout_error(e)
                    else f"Error al realizar búsquedas para la categoría {cat_id}. Se conservó el lote anterior."
                )
                logger.error("Error en búsqueda para categoría %s (%s)", cat_id, type(e).__name__)
                cat_aborted[cat_id] = True
                cat_abort_error[cat_id] = PublicStageError(
                    stage="discovery", code=err_code, message=err_msg, category_id=cat_id
                )

        return (
            searches_executed,
            quota_exhausted,
            raw_items_by_cat,
            cat_aborted,
            cat_abort_error,
            scheduled_counts,
            completed_counts,
        )

    def _hydrate_category(
        self, access_token: str, cat_id: int, unique_items: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[PublicStageError], bool]:
        """Hidrata videos y canales de una categoría aceptando HydrationResult o list."""
        video_ids = [item["youtube_video_id"] for item in unique_items]
        channel_ids = list({item["youtube_channel_id"] for item in unique_items})

        try:
            videos_details = self.gateway.get_videos_details(access_token, video_ids)
            if isinstance(videos_details, HydrationResult):
                v_details_list = videos_details.items
                v_complete = videos_details.complete
            else:
                v_details_list = videos_details
                v_complete = True

            if not v_complete:
                logger.error("Hidratación de videos incompleta para categoría %s", cat_id)
                err = PublicStageError(
                    stage="discovery",
                    code="EXTERNAL_ERROR",
                    message=f"Error al hidratar videos para la categoría {cat_id}. Se conservó el lote anterior.",
                    category_id=cat_id,
                )
                return None, None, err, False

            v_details_map = {vd["youtube_video_id"]: vd for vd in v_details_list}
        except YouTubeQuotaError:
            logger.error("Cuota agotada al hidratar videos en categoría %s", cat_id)
            err = PublicStageError(
                stage="discovery",
                code="YOUTUBE_QUOTA_EXHAUSTED",
                message="Se agotó la cuota de la API de YouTube. Se conservó el lote anterior.",
                category_id=cat_id,
            )
            return None, None, err, True
        except Exception as ev:
            err_code = "YOUTUBE_TIMEOUT" if _is_timeout_error(ev) else "EXTERNAL_ERROR"
            err_msg = (
                "YouTube no respondió a tiempo. Se conservó el lote anterior."
                if _is_timeout_error(ev)
                else f"Error al hidratar videos para la categoría {cat_id}. Se conservó el lote anterior."
            )
            logger.error("Error al hidratar videos para categoría %s (%s)", cat_id, type(ev).__name__)
            err = PublicStageError(stage="discovery", code=err_code, message=err_msg, category_id=cat_id)
            return None, None, err, False

        try:
            channels_details = self.gateway.get_channels_details(access_token, channel_ids)
            if isinstance(channels_details, HydrationResult):
                c_details_list = channels_details.items
                c_complete = channels_details.complete
            else:
                c_details_list = channels_details
                c_complete = True

            if not c_complete:
                logger.error("Hidratación de canales incompleta para categoría %s", cat_id)
                err = PublicStageError(
                    stage="discovery",
                    code="EXTERNAL_ERROR",
                    message=f"Error al hidratar canales para la categoría {cat_id}. Se conservó el lote anterior.",
                    category_id=cat_id,
                )
                return None, None, err, False

            c_details_map = {cd["youtube_channel_id"]: cd for cd in c_details_list}
        except YouTubeQuotaError:
            logger.error("Cuota agotada al hidratar canales en categoría %s", cat_id)
            err = PublicStageError(
                stage="discovery",
                code="YOUTUBE_QUOTA_EXHAUSTED",
                message="Se agotó la cuota de la API de YouTube. Se conservó el lote anterior.",
                category_id=cat_id,
            )
            return None, None, err, True
        except Exception as ec:
            err_code = "YOUTUBE_TIMEOUT" if _is_timeout_error(ec) else "EXTERNAL_ERROR"
            err_msg = (
                "YouTube no respondió a tiempo. Se conservó el lote anterior."
                if _is_timeout_error(ec)
                else f"Error al hidratar canales para la categoría {cat_id}. Se conservó el lote anterior."
            )
            logger.error("Error al hidratar canales para categoría %s (%s)", cat_id, type(ec).__name__)
            err = PublicStageError(stage="discovery", code=err_code, message=err_msg, category_id=cat_id)
            return None, None, err, False

        return v_details_map, c_details_map, None, False

    def _score_and_select_category(
        self,
        db,
        cat_id: int,
        signals: Any,
        unique_items: List[Dict[str, Any]],
        v_details_map: Dict[str, Any],
        c_details_map: Dict[str, Any],
        now: datetime,
        config: Dict[str, Any],
    ) -> CategoryAttemptResult:
        """Puntúa y selecciona el lote para una categoría."""
        candidates_data = []
        for item in unique_items:
            v_id = item["youtube_video_id"]
            c_id = item["youtube_channel_id"]
            v_det = v_details_map.get(v_id)
            c_det = c_details_map.get(c_id)

            if not v_det or not c_det:
                continue
            if v_det.get("duration_seconds") is None or v_det["duration_seconds"] <= 180:
                continue

            c_row = db.execute("SELECT id FROM channels WHERE youtube_channel_id = ?", (c_id,)).fetchone()
            cid = c_row["id"] if c_row else None
            v_row = db.execute("SELECT id FROM videos WHERE youtube_video_id = ?", (v_id,)).fetchone()
            vid = v_row["id"] if v_row else None

            video_eval = {
                "video_id": vid,
                "youtube_video_id": v_id,
                "channel_id": cid,
                "youtube_channel_id": c_id,
                "channel_title": c_det.get("title") or item["channel_title"],
                "title": item["title"],
                "description": item["description"],
                "published_at": item["published_at"],
                "duration_seconds": v_det["duration_seconds"],
                "thumbnail_url": item["thumbnail_url"],
                "content_type": v_det.get("content_type", "video"),
            }

            candidate = score_and_classify_candidate(
                video_eval,
                signals,
                now=now,
                min_score_related=config["min_related"],
                min_score_adjacent=config["min_adjacent"],
                min_score_exploratory=config["min_exploratory"],
            )
            if candidate:
                candidate.category_id = cat_id
                candidates_data.append((
                    candidate,
                    {
                        "youtube_channel_id": c_id,
                        "title": c_det.get("title") or item["channel_title"],
                        "description": c_det.get("description") or "",
                        "thumbnail_url": c_det.get("thumbnail_url") or item["thumbnail_url"],
                    },
                    {
                        "youtube_video_id": v_id,
                        "title": item["title"],
                        "description": item["description"],
                        "published_at": item["published_at"],
                        "thumbnail_url": item["thumbnail_url"],
                        "duration_seconds": v_det["duration_seconds"],
                        "content_type": v_det.get("content_type", "video"),
                    },
                ))

        candidates_pool = [t[0] for t in candidates_data]
        selected, counts, shortfall = select_batch_diverse(
            candidates_pool,
            target_total=config["batch_size"],
            target_related=config["mix_related"],
            target_adjacent=config["mix_adjacent"],
            target_exploratory=config["mix_exploratory"],
            max_videos_per_channel=config["max_videos_per_channel"],
        )
        selected_tuples = [t for t in candidates_data if t[0] in selected]

        target_total = config["batch_size"]
        selected_total = len(selected)
        shortfall_reason = None if selected_total == target_total else (shortfall or "insufficient_candidates")

        return CategoryAttemptResult(
            category_id=cat_id,
            outcome="publishable",
            candidates=selected,
            summary={
                "targetByBand": {
                    "related": config["mix_related"],
                    "adjacent": config["mix_adjacent"],
                    "exploratory": config["mix_exploratory"],
                },
                "selectedByBand": counts["selectedByBand"],
                "shortfall_reason": shortfall_reason,
            },
            selected_items_data=selected_tuples,
        )

    def _publish_category(
        self, db_path: str, run_id: int, cat_id: int, attempt: CategoryAttemptResult
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Publica atómicamente una categoría en SQLite (incluyendo lotes vacíos)."""
        if attempt.outcome == "aborted":
            err_dict = attempt.error.to_dict() if attempt.error else None
            shortfall_code = attempt.error.code.lower() if attempt.error else "external_error"
            return {"selected": 0, "shortfall": shortfall_code, "failed": True}, err_dict

        if attempt.summary:
            target_by_band = attempt.summary.get("targetByBand", {})
            selected_by_band = attempt.summary.get("selectedByBand", {})
            target_total = sum(target_by_band.values()) if target_by_band else 0
            selected_total = sum(selected_by_band.values()) if selected_by_band else len(attempt.candidates)

            shortfall = attempt.summary.get("shortfall_reason")
            if shortfall != "insufficient_signals":
                if selected_total == target_total and target_total > 0:
                    shortfall = None
                elif selected_total < target_total and not shortfall:
                    shortfall = "insufficient_candidates"
        else:
            shortfall = "insufficient_candidates"

        from app.db import get_db_connection

        cat_conn = get_db_connection(db_path)
        try:
            cat_conn.execute("BEGIN IMMEDIATE")

            for candidate, chan_data, video_data in attempt.selected_items_data:
                cid, vid = DiscoveryRepository.upsert_channel_and_video(cat_conn, chan_data, video_data)
                candidate.channel_id = cid
                candidate.video_id = vid
                DiscoveryRepository.save_discovery_candidate(cat_conn, candidate, run_id)

            counts_dict = {
                "targetByBand": attempt.summary["targetByBand"] if attempt.summary else {},
                "selectedByBand": attempt.summary["selectedByBand"] if attempt.summary else {},
            }
            DiscoveryRepository.save_discovery_batch(cat_conn, run_id, cat_id, counts_dict, shortfall)
            DiscoveryRepository.expire_previous_candidates(cat_conn, cat_id, run_id)

            cat_conn.commit()
            return {"selected": len(attempt.candidates), "shortfall": shortfall, "failed": False}, None
        except Exception as e:
            cat_conn.rollback()
            logger.exception("Error al publicar lote para categoría %s: %s", cat_id, type(e).__name__)
            err = PublicStageError(
                stage="discovery",
                code="EXTERNAL_ERROR",
                message=f"Error al publicar el lote de la categoría {cat_id}. Se conservó el lote anterior.",
                category_id=cat_id,
            )
            return {"selected": 0, "shortfall": "external_error", "failed": True}, err.to_dict()
        finally:
            cat_conn.close()

    def _evaluate_all_attempts(
        self,
        db,
        category_ids: List[int],
        category_signals: Dict[int, Any],
        cat_aborted: Dict[int, bool],
        cat_abort_error: Dict[int, Optional[PublicStageError]],
        raw_items_by_cat: Dict[int, Dict[str, Any]],
        access_token: str,
        now: datetime,
        config: Dict[str, Any],
    ) -> Tuple[Dict[int, CategoryAttemptResult], bool]:
        """Evalúa e hidrata los intentos de cada categoría."""
        attempt_results: Dict[int, CategoryAttemptResult] = {}
        hydration_quota_exhausted = False

        for cat_id in category_ids:
            if hydration_quota_exhausted:
                err = PublicStageError(
                    stage="discovery",
                    code="YOUTUBE_QUOTA_EXHAUSTED",
                    message="Se agotó la cuota de la API de YouTube. Se conservó el lote anterior.",
                    category_id=cat_id,
                )
                attempt_results[cat_id] = CategoryAttemptResult(category_id=cat_id, outcome="aborted", error=err)
                continue

            signals = category_signals[cat_id]
            if not signals.positive_keywords and not signals.seed_channel_ids:
                attempt_results[cat_id] = CategoryAttemptResult(
                    category_id=cat_id,
                    outcome="publishable",
                    candidates=[],
                    summary={
                        "targetByBand": {
                            "related": config["mix_related"],
                            "adjacent": config["mix_adjacent"],
                            "exploratory": config["mix_exploratory"],
                        },
                        "selectedByBand": {"related": 0, "adjacent": 0, "exploratory": 0},
                        "shortfall_reason": "insufficient_signals",
                    },
                )
                continue

            if cat_aborted[cat_id]:
                attempt_results[cat_id] = CategoryAttemptResult(
                    category_id=cat_id, outcome="aborted", error=cat_abort_error[cat_id]
                )
                continue

            unique_items = list(raw_items_by_cat[cat_id].values())
            if not unique_items:
                attempt_results[cat_id] = CategoryAttemptResult(
                    category_id=cat_id,
                    outcome="publishable",
                    candidates=[],
                    summary={
                        "targetByBand": {
                            "related": config["mix_related"],
                            "adjacent": config["mix_adjacent"],
                            "exploratory": config["mix_exploratory"],
                        },
                        "selectedByBand": {"related": 0, "adjacent": 0, "exploratory": 0},
                        "shortfall_reason": "insufficient_candidates",
                    },
                )
                continue

            v_map, c_map, hyd_err, is_quota = self._hydrate_category(access_token, cat_id, unique_items)
            if is_quota:
                hydration_quota_exhausted = True
                attempt_results[cat_id] = CategoryAttemptResult(category_id=cat_id, outcome="aborted", error=hyd_err)
                continue

            if hyd_err:
                attempt_results[cat_id] = CategoryAttemptResult(category_id=cat_id, outcome="aborted", error=hyd_err)
                continue

            attempt_results[cat_id] = self._score_and_select_category(
                db, cat_id, signals, unique_items, v_map, c_map, now, config
            )

        return attempt_results, hydration_quota_exhausted

    def run_discovery(self, db, run_id: int, heartbeat_callback=None) -> dict:
        """Ejecuta la canalización de descubrimiento en 5 pasos."""
        sub_service = SubscriptionService(gateway=self.gateway)
        access_token = sub_service._get_valid_access_token(db)

        from flask import current_app

        config = {
            "global_budget": current_app.config.get("DISCOVERY_MAX_SEARCHES_PER_REFRESH", 10),
            "category_budget": current_app.config.get("DISCOVERY_MAX_SEARCHES_PER_CATEGORY", 2),
            "signal_window": current_app.config.get("DISCOVERY_SIGNAL_WINDOW_DAYS", 90),
            "search_age_days": current_app.config.get("DISCOVERY_MAX_SEARCH_AGE_DAYS", 180),
            "batch_size": current_app.config.get("DISCOVERY_BATCH_SIZE", 8),
            "mix_related": current_app.config.get("DISCOVERY_MIX_RELATED", 5),
            "mix_adjacent": current_app.config.get("DISCOVERY_MIX_ADJACENT", 2),
            "mix_exploratory": current_app.config.get("DISCOVERY_MIX_EXPLORATORY", 1),
            "max_videos_per_channel": current_app.config.get("DISCOVERY_MAX_VIDEOS_PER_CHANNEL", 2),
            "results_per_search": current_app.config.get("DISCOVERY_RESULTS_PER_SEARCH", 25),
            "region_code": current_app.config.get("DISCOVERY_REGION_CODE", "AR"),
            "relevance_language": current_app.config.get("DISCOVERY_RELEVANCE_LANGUAGE", "es"),
            "min_related": current_app.config.get("DISCOVERY_MIN_SCORE_RELATED", 55.0),
            "min_adjacent": current_app.config.get("DISCOVERY_MIN_SCORE_ADJACENT", 45.0),
            "min_exploratory": current_app.config.get("DISCOVERY_MIN_SCORE_EXPLORATORY", 35.0),
        }

        now = datetime.now(timezone.utc)
        published_after = (now - timedelta(days=config["search_age_days"])).isoformat()[:19] + "Z"

        cursor = db.execute("SELECT id FROM categories ORDER BY position ASC")
        category_ids = [row["id"] for row in cursor.fetchall()]

        category_signals, category_queries = self._prepare_snapshots_and_queries(
            db, category_ids, config["category_budget"], config["signal_window"]
        )

        scheduled_tasks = schedule_queries_round_robin(
            category_queries, global_budget=config["global_budget"], max_per_category=config["category_budget"]
        )

        (
            searches_executed,
            quota_exhausted,
            raw_items_by_cat,
            cat_aborted,
            cat_abort_error,
            scheduled_counts,
            completed_counts,
        ) = self._execute_searches(
            access_token,
            scheduled_tasks,
            published_after,
            config["results_per_search"],
            config["region_code"],
            config["relevance_language"],
            category_ids,
            heartbeat_callback,
        )

        for cat_id in category_ids:
            if scheduled_counts[cat_id] > 0 and completed_counts[cat_id] < scheduled_counts[cat_id]:
                cat_aborted[cat_id] = True
                if not cat_abort_error[cat_id]:
                    cat_abort_error[cat_id] = PublicStageError(
                        stage="discovery",
                        code="YOUTUBE_QUOTA_EXHAUSTED" if quota_exhausted else "EXTERNAL_ERROR",
                        message="Se agotó la cuota de la API de YouTube. Se conservó el lote anterior.",
                        category_id=cat_id,
                    )

        attempt_results, hyd_quota = self._evaluate_all_attempts(
            db,
            category_ids,
            category_signals,
            cat_aborted,
            cat_abort_error,
            raw_items_by_cat,
            access_token,
            now,
            config,
        )

        db_path = current_app.config["DATABASE_PATH"]
        stats_by_category = {}
        public_errors = []

        for cat_id in category_ids:
            attempt = attempt_results[cat_id]
            cat_stat, err_dict = self._publish_category(db_path, run_id, cat_id, attempt)
            stats_by_category[cat_id] = cat_stat
            if err_dict:
                public_errors.append(err_dict)

        return {
            "searches_executed": searches_executed,
            "quota_exhausted": quota_exhausted or hyd_quota,
            "categories": stats_by_category,
            "errors": public_errors,
        }
