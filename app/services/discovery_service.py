import logging
from datetime import datetime, timedelta, timezone

from app.domain.discovery.query_builder import build_queries_for_category, schedule_queries_round_robin
from app.domain.discovery.scoring import score_and_classify_candidate
from app.domain.discovery.selection import select_batch_diverse
from app.integrations.youtube.gateway import YouTubeGateway, YouTubeQuotaError
from app.repositories.discovery_repository import DiscoveryRepository
from app.services.exploration_topic_service import ExplorationTopicService
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

class DiscoveryService:
    def __init__(self, gateway=None):
        self.gateway = gateway or YouTubeGateway()

    def run_discovery(self, db, run_id: int, heartbeat_callback=None) -> dict:
        """
        Ejecuta el motor de descubrimiento para todas las categorías.
        - Genera consultas en round-robin.
        - Busca candidatos usando YouTube API.
        - Filtra, puntúa y selecciona lote 5/2/1.
        - Guarda lotes de forma transaccional.
        """
        # 1. Validar token
        sub_service = SubscriptionService(gateway=self.gateway)
        try:
            access_token = sub_service._get_valid_access_token(db)
        except Exception as e:
            logger.error(f"No se pudo obtener access token para descubrimiento: {e}")
            raise e

        # 2. Cargar configuraciones de presupuestos
        from flask import current_app
        global_budget = current_app.config.get("DISCOVERY_MAX_SEARCHES_PER_REFRESH", 10)
        category_budget = current_app.config.get("DISCOVERY_MAX_SEARCHES_PER_CATEGORY", 2)
        signal_window = current_app.config.get("DISCOVERY_SIGNAL_WINDOW_DAYS", 90)
        search_age_days = current_app.config.get("DISCOVERY_MAX_SEARCH_AGE_DAYS", 180)

        # Configuración de mezcla y selección
        batch_size = current_app.config.get("DISCOVERY_BATCH_SIZE", 8)
        mix_related = current_app.config.get("DISCOVERY_MIX_RELATED", 5)
        mix_adjacent = current_app.config.get("DISCOVERY_MIX_ADJACENT", 2)
        mix_exploratory = current_app.config.get("DISCOVERY_MIX_EXPLORATORY", 1)
        max_videos_per_channel = current_app.config.get("DISCOVERY_MAX_VIDEOS_PER_CHANNEL", 2)
        results_per_search = current_app.config.get("DISCOVERY_RESULTS_PER_SEARCH", 25)
        region_code = current_app.config.get("DISCOVERY_REGION_CODE", "AR")
        relevance_language = current_app.config.get("DISCOVERY_RELEVANCE_LANGUAGE", "es")

        # Umbrales
        min_related = current_app.config.get("DISCOVERY_MIN_SCORE_RELATED", 55.0)
        min_adjacent = current_app.config.get("DISCOVERY_MIN_SCORE_ADJACENT", 45.0)
        min_exploratory = current_app.config.get("DISCOVERY_MIN_SCORE_EXPLORATORY", 35.0)

        now = datetime.now(timezone.utc)
        published_after = (now - timedelta(days=search_age_days)).isoformat()[:19] + "Z"

        # 3. Obtener categorías
        cursor = db.execute("SELECT id FROM categories ORDER BY position ASC")
        category_ids = [row["id"] for row in cursor.fetchall()]

        category_queries = {}
        category_signals = {}

        # 4. Registrar propuestas automáticas y armar snapshot de señales
        for cat_id in category_ids:
            try:
                ExplorationTopicService.generate_automatic_proposals(db, cat_id)
            except Exception as e:
                logger.warning(f"Error generando propuestas de temas para categoría {cat_id}: {e}")

            signals = DiscoveryRepository.get_category_signals(db, cat_id, signal_window_days=signal_window)
            category_signals[cat_id] = signals

            queries = build_queries_for_category(signals, max_queries=category_budget)
            category_queries[cat_id] = queries

        # 5. Programar en round-robin
        scheduled_tasks = schedule_queries_round_robin(category_queries, global_budget=global_budget, max_per_category=category_budget)

        # Track scheduled counts
        scheduled_counts = {cat_id: 0 for cat_id in category_ids}
        for cat_id, _ in scheduled_tasks:
            scheduled_counts[cat_id] += 1

        successful_counts = {cat_id: 0 for cat_id in category_ids}
        category_failed = {cat_id: False for cat_id in category_ids}
        category_failure_reason = {cat_id: None for cat_id in category_ids}

        quota_exhausted = False
        searches_executed = 0

        # Guardar candidatos encontrados por categoría
        raw_items_by_category = {cat_id: {} for cat_id in category_ids}

        # 6. Ejecutar búsquedas
        # 6. Ejecutar búsquedas
        for cat_id, q_task in scheduled_tasks:
            if heartbeat_callback:
                heartbeat_callback()

            if quota_exhausted or category_failed[cat_id]:
                category_failed[cat_id] = True
                category_failure_reason[cat_id] = "quota_exhausted" if quota_exhausted else category_failure_reason[cat_id]
                continue

            q_str = q_task["q"]
            logger.info(f"Ejecutando búsqueda para categoría {cat_id}: '{q_str}'")

            try:
                # Llamada externa a YouTube
                items = self.gateway.search_videos(
                    access_token,
                    q=q_str,
                    published_after=published_after,
                    limit=results_per_search,
                    region_code=region_code,
                    relevance_language=relevance_language
                )
                searches_executed += 1
                successful_counts[cat_id] += 1

                for item in items:
                    v_id = item["youtube_video_id"]
                    raw_items_by_category[cat_id][v_id] = item

            except YouTubeQuotaError as eq:
                logger.error(f"Cuota de YouTube agotada: {eq}")
                quota_exhausted = True
                category_failed[cat_id] = True
                category_failure_reason[cat_id] = "quota_exhausted"
            except Exception as e:
                logger.error(f"Error ejecutando consulta '{q_str}' para categoría {cat_id}: {e}")
                category_failed[cat_id] = True
                category_failure_reason[cat_id] = "external_error"

        # 7. Hidratar, puntuar, seleccionar y persistir lotes por categoría
        stats_by_category = {}

        for cat_id in category_ids:
            # Si tiene búsquedas programadas pero menos completadas exitosamente, la categoría falló
            if scheduled_counts[cat_id] > 0 and successful_counts[cat_id] < scheduled_counts[cat_id]:
                category_failed[cat_id] = True
                if not category_failure_reason[cat_id]:
                    category_failure_reason[cat_id] = "external_error"

            signals = category_signals[cat_id]
            unique_items = list(raw_items_by_category[cat_id].values())

            # Si no había palabras clave o señales
            if not signals.positive_keywords and not signals.seed_channel_ids:
                from flask import current_app

                from app.db import get_db_connection
                db_path = current_app.config["DATABASE_PATH"]
                cat_conn = get_db_connection(db_path)
                try:
                    cat_conn.execute("BEGIN IMMEDIATE")
                    DiscoveryRepository.save_discovery_batch(
                        cat_conn, run_id, cat_id,
                        {"targetByBand": {"related": mix_related, "adjacent": mix_adjacent, "exploratory": mix_exploratory},
                         "selectedByBand": {"related": 0, "adjacent": 0, "exploratory": 0}},
                        shortfall_reason="insufficient_signals"
                    )
                    cat_conn.commit()
                    stats_by_category[cat_id] = {"selected": 0, "shortfall": "insufficient_signals", "failed": False}
                except Exception as e:
                    cat_conn.rollback()
                    logger.error(f"Error al guardar batch vacío para categoría {cat_id}: {e}")
                    stats_by_category[cat_id] = {"selected": 0, "shortfall": "external_error", "failed": True}
                finally:
                    cat_conn.close()
                continue

            if category_failed[cat_id]:
                logger.warning(f"Categoría {cat_id} falló durante la búsqueda. Se conserva el lote anterior. Motivo: {category_failure_reason[cat_id]}")
                stats_by_category[cat_id] = {
                    "selected": 0,
                    "shortfall": category_failure_reason[cat_id],
                    "failed": True
                }
                continue

            if not unique_items:
                stats_by_category[cat_id] = {"selected": 0, "shortfall": "no_results", "failed": False}
                continue

            # Batch hydrate videos y channels
            video_ids = [item["youtube_video_id"] for item in unique_items]
            channel_ids = list({item["youtube_channel_id"] for item in unique_items})

            try:
                videos_details = self.gateway.get_videos_details(access_token, video_ids)
                v_details_map = {vd["youtube_video_id"]: vd for vd in videos_details}
            except Exception as ev:
                logger.error(f"Error al hidratar videos para categoría {cat_id}: {ev}")
                category_failed[cat_id] = True
                category_failure_reason[cat_id] = "external_error"
                v_details_map = {}

            try:
                channels_details = self.gateway.get_channels_details(access_token, channel_ids)
                c_details_map = {cd["youtube_channel_id"]: cd for cd in channels_details}
            except Exception as ec:
                logger.error(f"Error al hidratar canales para categoría {cat_id}: {ec}")
                category_failed[cat_id] = True
                category_failure_reason[cat_id] = "external_error"
                c_details_map = {}

            if category_failed[cat_id]:
                logger.warning(f"Categoría {cat_id} falló durante hidratación. Se conserva el lote anterior. Motivo: {category_failure_reason[cat_id]}")
                stats_by_category[cat_id] = {
                    "selected": 0,
                    "shortfall": category_failure_reason[cat_id],
                    "failed": True
                }
                continue

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

                # Query database IDs without creating write locks
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
                    "content_type": v_det.get("content_type", "video")
                }

                candidate = score_and_classify_candidate(
                    video_eval,
                    signals,
                    now=now,
                    min_score_related=min_related,
                    min_score_adjacent=min_adjacent,
                    min_score_exploratory=min_exploratory
                )
                if candidate:
                    candidate.category_id = cat_id
                    # Conservar datos de canal/video hidratados para hacer el upsert después
                    candidates_data.append((candidate, {
                        "youtube_channel_id": c_id,
                        "title": c_det.get("title") or item["channel_title"],
                        "description": c_det.get("description") or "",
                        "thumbnail_url": c_det.get("thumbnail_url") or item["thumbnail_url"]
                    }, {
                        "youtube_video_id": v_id,
                        "title": item["title"],
                        "description": item["description"],
                        "published_at": item["published_at"],
                        "thumbnail_url": item["thumbnail_url"],
                        "duration_seconds": v_det["duration_seconds"],
                        "content_type": v_det.get("content_type", "video")
                    }))

            # Seleccionar lote diverso
            candidates = [cd[0] for cd in candidates_data]
            selected, counts, shortfall = select_batch_diverse(
                candidates,
                target_total=batch_size,
                target_related=mix_related,
                target_adjacent=mix_adjacent,
                target_exploratory=mix_exploratory,
                max_videos_per_channel=max_videos_per_channel
            )

            # Degradación segura: Si el nuevo lote queda vacío (0 candidatos), NO lo persistimos
            # ni expiramos las recomendaciones anteriores. Conservamos el lote previo intacto.
            if len(selected) == 0:
                logger.warning(
                f"Categoría {cat_id} no produjo candidatos nuevos válidos. "
                f"Se conserva el lote anterior. Motivo: {shortfall or 'no_results'}"
            )
                stats_by_category[cat_id] = {
                    "selected": 0,
                    "shortfall": shortfall or "no_results",
                    "failed": False
                }
                continue

            # Persistir candidatos de manera transaccional por categoría
            from flask import current_app

            from app.db import get_db_connection
            db_path = current_app.config["DATABASE_PATH"]
            cat_conn = get_db_connection(db_path)
            try:
                cat_conn.execute("BEGIN IMMEDIATE")

                # Upsert de canal/video y setear ids correctos en candidatos seleccionados
                for candidate in selected:
                    orig_tuple = next(t for t in candidates_data if t[0].youtube_video_id == candidate.youtube_video_id)
                    chan_data = orig_tuple[1]
                    video_data = orig_tuple[2]

                    cid, vid = DiscoveryRepository.upsert_channel_and_video(cat_conn, chan_data, video_data)
                    candidate.channel_id = cid
                    candidate.video_id = vid

                    DiscoveryRepository.save_discovery_candidate(cat_conn, candidate, run_id)

                # Guardar lote batch summary
                DiscoveryRepository.save_discovery_batch(cat_conn, run_id, cat_id, counts, shortfall)

                # Expirar candidatos del lote anterior de forma atómica en esta transacción
                DiscoveryRepository.expire_previous_candidates(cat_conn, cat_id, run_id)

                cat_conn.commit()

                stats_by_category[cat_id] = {
                    "selected": len(selected),
                    "shortfall": shortfall,
                    "failed": False
                }
            except Exception:
                cat_conn.rollback()
                logger.exception(f"Error al persistir lote para categoría {cat_id}:")
                stats_by_category[cat_id] = {
                    "selected": 0,
                    "shortfall": "external_error",
                    "failed": True
                }
            finally:
                cat_conn.close()

        return {
            "searches_executed": searches_executed,
            "quota_exhausted": quota_exhausted,
            "categories": stats_by_category
        }
