import json

from flask import Blueprint, current_app, jsonify, request

from app.db import get_db_connection
from app.domain.discovery.normalization import normalize_term
from app.repositories.discovery_repository import DiscoveryRepository
from app.repositories.exploration_topic_repository import ExplorationTopicRepository
from app.repositories.refresh_run_repository import RefreshRunRepository
from app.services.exploration_topic_service import ExplorationTopicService

discovery_bp = Blueprint("discovery", __name__)


def make_error_response(code: str, message: str, status_code: int, details: dict = None):
    """Retorna una respuesta de error estandarizada según el esquema Error de OpenAPI."""
    err_obj = {"code": code, "message": message}
    if details is not None:
        err_obj["details"] = details
    return jsonify({"error": err_obj}), status_code


def _serialize_run_counters(counters_raw):
    counters = {}
    if isinstance(counters_raw, dict):
        if "subscriptions" in counters_raw:
            counters["subscriptions"] = counters_raw["subscriptions"]
        if "followed_videos" in counters_raw:
            counters["followedVideos"] = counters_raw["followed_videos"]
        elif "followedVideos" in counters_raw:
            counters["followedVideos"] = counters_raw["followedVideos"]

        if "discovery" in counters_raw:
            disc = counters_raw["discovery"]
            if isinstance(disc, dict):
                counters["discovery"] = {
                    "searchesExecuted": disc.get("searches_executed", disc.get("searchesExecuted", 0)),
                    "quotaExhausted": disc.get("quota_exhausted", disc.get("quotaExhausted", False)),
                    "categories": disc.get("categories", {}),
                }
    return counters


def _serialize_run_errors(errors_raw):
    errors = []
    if isinstance(errors_raw, list):
        for err in errors_raw:
            if isinstance(err, dict):
                err_obj = {
                    "stage": err.get("stage", "discovery"),
                    "code": err.get("code", "UNKNOWN_ERROR"),
                    "message": err.get("message", ""),
                }
                if "categoryId" in err:
                    err_obj["categoryId"] = err["categoryId"]
                elif "category_id" in err and err["category_id"] is not None:
                    err_obj["categoryId"] = err["category_id"]
                errors.append(err_obj)
    elif isinstance(errors_raw, dict):
        for k, v in errors_raw.items():
            errors.append({"stage": k, "code": "STAGE_ERROR", "message": str(v)})
    return errors


def serialize_refresh_run(run_dict):
    """Serializa un registro de refresh_runs transformando claves a camelCase."""
    if not run_dict:
        return None

    try:
        stages = json.loads(run_dict.get("requested_stages_json") or "[]")
    except Exception:
        stages = []

    try:
        counters_raw = json.loads(run_dict.get("counters_json") or "{}")
    except Exception:
        counters_raw = {}

    try:
        errors_raw = json.loads(run_dict.get("errors_json") or "[]")
    except Exception:
        errors_raw = []

    return {
        "id": run_dict["id"],
        "status": run_dict["status"],
        "currentStage": run_dict.get("current_stage"),
        "stages": stages,
        "requestedAt": run_dict.get("requested_at"),
        "startedAt": run_dict.get("started_at"),
        "finishedAt": run_dict.get("finished_at"),
        "counters": _serialize_run_counters(counters_raw),
        "errors": _serialize_run_errors(errors_raw),
        "heartbeatAt": run_dict.get("heartbeat_at"),
        "leaseExpiresAt": run_dict.get("lease_expires_at"),
    }


def _serialize_channel(row):
    r_dict = dict(row) if not isinstance(row, dict) else row
    cat_ids = []
    if "category_ids" in r_dict and r_dict["category_ids"]:
        if isinstance(r_dict["category_ids"], str):
            cat_ids = [int(x) for x in r_dict["category_ids"].split(",") if x]
        else:
            cat_ids = list(r_dict["category_ids"])
    elif "categoryIds" in r_dict and r_dict["categoryIds"]:
        cat_ids = list(r_dict["categoryIds"])

    return {
        "id": r_dict["id"],
        "youtubeChannelId": r_dict["youtube_channel_id"],
        "title": r_dict["title"],
        "description": r_dict.get("description") or "",
        "thumbnailUrl": r_dict.get("thumbnail_url") or None,
        "subscribed": bool(r_dict.get("is_subscribed", 0)),
        "locallyFollowed": bool(r_dict.get("is_locally_followed", 0)),
        "blocked": bool(r_dict.get("is_blocked", 0)),
        "categoryIds": cat_ids,
    }


def _serialize_video(row, channel_row, category_ids):
    r_dict = dict(row) if not isinstance(row, dict) else row
    c_dict = dict(channel_row) if not isinstance(channel_row, dict) else channel_row
    is_followed = bool(c_dict.get("is_subscribed", 0)) or bool(c_dict.get("is_locally_followed", 0))
    origin = "followed" if is_followed else "discovery"
    return {
        "id": r_dict["id"],
        "youtubeVideoId": r_dict["youtube_video_id"],
        "channel": _serialize_channel({**c_dict, "categoryIds": category_ids}),
        "title": r_dict["title"],
        "description": r_dict.get("description") or "",
        "publishedAt": r_dict["published_at"],
        "durationSeconds": r_dict.get("duration_seconds"),
        "thumbnailUrl": r_dict.get("thumbnail_url") or None,
        "contentType": r_dict.get("content_type") or "video",
        "origin": origin,
        "watched": bool(r_dict.get("watched", 0)),
    }


def serialize_exploration_topic(topic_dict):
    if not topic_dict:
        return None
    return {
        "id": topic_dict["id"],
        "categoryId": topic_dict["category_id"],
        "term": topic_dict["term"],
        "weight": topic_dict["weight"],
        "source": topic_dict["source"],
        "status": topic_dict["status"],
        "rationale": topic_dict.get("rationale"),
        "createdAt": topic_dict["created_at"],
        "updatedAt": topic_dict["updated_at"],
    }


@discovery_bp.route("/discoveries", methods=["GET"])
def list_discoveries():
    cat_id_raw = request.args.get("categoryId")
    band = request.args.get("band", default="all")
    offset = request.args.get("cursor", default="0")
    limit_raw = request.args.get("limit", default="25")

    try:
        offset_int = int(offset)
        if offset_int < 0:
            raise ValueError()
    except (ValueError, TypeError):
        return make_error_response("VALIDATION_ERROR", "El parámetro cursor debe ser un entero no negativo.", 400)

    valid_bands = {"all", "related", "adjacent", "exploratory"}
    if band not in valid_bands:
        return make_error_response("VALIDATION_ERROR", f"Banda no válida: {band}", 400)

    try:
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            raise ValueError()
    except (ValueError, TypeError):
        return make_error_response("VALIDATION_ERROR", "El parámetro limit debe ser un entero entre 1 y 100.", 400)

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        if cat_id_raw is not None:
            try:
                cat_id = int(cat_id_raw)
            except (ValueError, TypeError):
                return make_error_response("VALIDATION_ERROR", "categoryId debe ser un entero.", 400)

            cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (cat_id,)).fetchone()
            if not cat_check:
                return make_error_response("NOT_FOUND", "Categoría no encontrada.", 404)
        else:
            cat_id = None

        recs, batches, next_cursor = DiscoveryRepository.get_active_batch_recommendations(
            db, category_id=cat_id, band=band, offset=offset_int, limit=limit
        )
        return jsonify({"items": recs, "batches": batches, "nextCursor": next_cursor})
    finally:
        db.close()


@discovery_bp.route("/discoveries/<int:video_id>/feedback", methods=["POST"])
def submit_discovery_feedback(video_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return make_error_response("VALIDATION_ERROR", "El cuerpo de la petición debe ser un objeto JSON.", 422)

    if "channelId" in body:
        return make_error_response(
            "VALIDATION_ERROR", "No se permite enviar channelId en la petición de feedback.", 422
        )

    category_id = body.get("categoryId")
    action = body.get("action")

    if category_id is None or isinstance(category_id, bool) or not isinstance(category_id, int):
        return make_error_response("VALIDATION_ERROR", "categoryId es obligatorio y debe ser un entero.", 422)

    valid_actions = {"more_like_this", "less_like_this", "hide_video", "block_channel", "accept_channel"}
    if not action or not isinstance(action, str) or action not in valid_actions:
        return make_error_response("VALIDATION_ERROR", f"Acción no válida: {action}", 422)

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        video = db.execute("SELECT id, channel_id FROM videos WHERE id = ?", (video_id,)).fetchone()
        if not video:
            return make_error_response("NOT_FOUND", "Video no encontrado.", 404)

        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return make_error_response("NOT_FOUND", "Categoría no encontrada.", 404)

        candidate = db.execute(
            "SELECT 1 FROM discovery_candidates WHERE video_id = ? AND category_id = ?",
            (video_id, category_id),
        ).fetchone()
        if not candidate:
            return make_error_response(
                "NOT_FOUND", "Candidato de descubrimiento no encontrado para esta categoría.", 404
            )

        channel_id = video["channel_id"]

        DiscoveryRepository.save_feedback(
            db, video_id=video_id, channel_id=channel_id, category_id=category_id, action=action
        )
        db.commit()
        return jsonify({"applied": True})
    finally:
        db.close()


@discovery_bp.route("/discoveries/<int:video_id>/hidden", methods=["DELETE"])
def restore_hidden_discovery(video_id):
    cat_id_raw = request.args.get("categoryId")
    if not cat_id_raw:
        return make_error_response("VALIDATION_ERROR", "Falta categoryId.", 400)

    try:
        category_id = int(cat_id_raw)
    except (ValueError, TypeError):
        return make_error_response("VALIDATION_ERROR", "categoryId debe ser un entero.", 400)

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        video_check = db.execute("SELECT 1 FROM videos WHERE id = ?", (video_id,)).fetchone()
        if not video_check:
            return make_error_response("NOT_FOUND", "Video no encontrado.", 404)

        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return make_error_response("NOT_FOUND", "Categoría no encontrada.", 404)

        candidate_check = db.execute(
            "SELECT 1 FROM discovery_candidates WHERE video_id = ? AND category_id = ? AND status = 'hidden'",
            (video_id, category_id),
        ).fetchone()
        if not candidate_check:
            return make_error_response(
                "NOT_FOUND", "Candidato oculto no encontrado para esta categoría.", 404
            )

        db.execute(
            "DELETE FROM discovery_feedback WHERE video_id = ? AND category_id = ? AND action = 'hide_video'",
            (video_id, category_id),
        )
        db.execute(
            "UPDATE discovery_candidates SET status = 'active' "
            "WHERE video_id = ? AND category_id = ? AND status = 'hidden'",
            (video_id, category_id),
        )
        db.commit()
        return "", 204
    finally:
        db.close()


@discovery_bp.route("/settings/discovery-exclusions", methods=["GET"])
def list_discovery_exclusions():
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        cursor = db.execute("""
            SELECT c.*, GROUP_CONCAT(cc.category_id) as category_ids
            FROM channels c
            LEFT JOIN channel_categories cc ON c.id = cc.channel_id
            WHERE c.is_blocked = 1
            GROUP BY c.id
        """)
        blocked_channels = [_serialize_channel(dict(row)) for row in cursor.fetchall()]

        cursor = db.execute("""
            SELECT
                v.id, v.youtube_video_id, v.title, v.description, v.published_at, v.duration_seconds,
                v.thumbnail_url, v.content_type,
                ch.id as channel_id, ch.youtube_channel_id, ch.title as channel_title,
                ch.description as channel_description,
                ch.thumbnail_url as channel_thumbnail, ch.is_subscribed, ch.is_locally_followed, ch.is_blocked,
                df.category_id, df.created_at as hidden_at,
                COALESCE(vus.watched, 0) as watched
            FROM discovery_feedback df
            JOIN videos v ON df.video_id = v.id
            JOIN channels ch ON v.channel_id = ch.id
            LEFT JOIN video_user_state vus ON v.id = vus.video_id
            WHERE df.action = 'hide_video'
        """)

        hidden_videos = []
        for row in cursor.fetchall():
            channel_row = {
                "id": row["channel_id"],
                "youtube_channel_id": row["youtube_channel_id"],
                "title": row["channel_title"],
                "description": row["channel_description"],
                "thumbnail_url": row["channel_thumbnail"],
                "is_subscribed": row["is_subscribed"],
                "is_locally_followed": row["is_locally_followed"],
                "is_blocked": row["is_blocked"],
            }
            cat_assigned = db.execute(
                "SELECT category_id FROM channel_categories WHERE channel_id = ?", (row["channel_id"],)
            ).fetchall()
            cat_ids = [r["category_id"] for r in cat_assigned]

            video_obj = _serialize_video(row, channel_row, cat_ids)
            hidden_videos.append({"video": video_obj, "categoryId": row["category_id"], "hiddenAt": row["hidden_at"]})

        return jsonify({"blockedChannels": blocked_channels, "hiddenVideos": hidden_videos})
    finally:
        db.close()


@discovery_bp.route("/refresh-runs", methods=["GET"])
def list_refresh_runs():
    limit_raw = request.args.get("limit", default="30")
    try:
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            raise ValueError()
    except (ValueError, TypeError):
        return make_error_response("VALIDATION_ERROR", "El parámetro limit debe ser un entero entre 1 y 100.", 400)

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        runs = RefreshRunRepository.list_all(db)[:limit]
        return jsonify({"items": [serialize_refresh_run(r) for r in runs]})
    finally:
        db.close()


@discovery_bp.route("/refresh-runs", methods=["POST"])
def start_refresh():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    elif not isinstance(body, dict):
        return make_error_response("VALIDATION_ERROR", "El cuerpo debe ser un objeto JSON.", 422)

    stages = body.get("stages")
    valid_stages = {"subscriptions", "followed_videos", "discovery"}

    if stages is not None:
        if not isinstance(stages, list):
            return make_error_response("VALIDATION_ERROR", "El campo stages debe ser una lista.", 422)
        for s in stages:
            if not isinstance(s, str) or s not in valid_stages:
                return make_error_response("VALIDATION_ERROR", f"Etapa desconocida: {s}", 422)
    else:
        stages = ["subscriptions", "followed_videos", "discovery"]

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        if RefreshRunRepository.has_active_run(db):
            return make_error_response("CONFLICT", "Ya hay una actualización activa en curso.", 409)

        run_id = RefreshRunRepository.create(db, stages)
        db.commit()
        run = RefreshRunRepository.get_by_id(db, run_id)
        return jsonify(serialize_refresh_run(run)), 202
    finally:
        db.close()


@discovery_bp.route("/refresh-runs/<int:run_id>", methods=["GET"])
def get_refresh_run(run_id):
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        run = RefreshRunRepository.get_by_id(db, run_id)
        if not run:
            return make_error_response("NOT_FOUND", "Actualización no encontrada.", 404)
        return jsonify(serialize_refresh_run(run))
    finally:
        db.close()


@discovery_bp.route("/refresh-runs/last-successful", methods=["GET"])
def get_last_successful_refresh_run():
    from datetime import datetime, timezone

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        run = RefreshRunRepository.get_last_successful_run(db)
        if not run:
            return jsonify({"lastSuccessfulRun": None, "isStale": True, "staleHoursThreshold": 24})

        serialized = serialize_refresh_run(run)
        stale_hours_threshold = 24
        is_stale = True
        finished_at_str = run.get("finished_at")
        if finished_at_str:
            try:
                finished_at = datetime.fromisoformat(finished_at_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                hours_diff = (now - finished_at).total_seconds() / 3600.0
                is_stale = hours_diff >= stale_hours_threshold
            except Exception:
                pass

        return jsonify({
            "lastSuccessfulRun": serialized,
            "isStale": is_stale,
            "staleHoursThreshold": stale_hours_threshold
        })
    finally:
        db.close()


@discovery_bp.route("/categories/<int:category_id>/exploration-topics", methods=["GET"])
def list_exploration_topics(category_id):
    status = request.args.get("status", default="all")
    if status not in {"all", "pending", "approved", "rejected"}:
        return make_error_response("VALIDATION_ERROR", f"Estado no válido: {status}", 400)

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return make_error_response("NOT_FOUND", "Categoría no encontrada.", 404)

        all_topics = ExplorationTopicService.list_topics(db, category_id)
        if status != "all":
            all_topics = [t for t in all_topics if t["status"] == status]
        return jsonify({"items": [serialize_exploration_topic(t) for t in all_topics]})
    finally:
        db.close()


@discovery_bp.route("/categories/<int:category_id>/exploration-topics", methods=["POST"])
def create_exploration_topic(category_id):
    body = request.get_json(silent=True) or {}
    term = body.get("term")
    weight = body.get("weight", 1.0)

    if not term or not isinstance(term, str) or not term.strip() or len(term) > 120:
        return make_error_response(
            "VALIDATION_ERROR", "El término es obligatorio y no puede exceder 120 caracteres.", 422
        )

    try:
        weight_val = float(weight)
        if weight_val < 0.0 or weight_val > 10.0:
            raise ValueError()
    except (ValueError, TypeError):
        return make_error_response("VALIDATION_ERROR", "El peso debe ser un número entre 0 y 10.", 422)

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return make_error_response("NOT_FOUND", "Categoría no encontrada.", 404)

        norm = normalize_term(term)
        existing = ExplorationTopicRepository.get_by_category_and_term(db, category_id, norm)
        if existing:
            return make_error_response("CONFLICT", "El tema ya existe en esta categoría.", 409)

        ExplorationTopicService.create_manual_topic(db, category_id, term, weight_val)
        db.commit()
        topic = ExplorationTopicRepository.get_by_category_and_term(db, category_id, norm)
        return jsonify(serialize_exploration_topic(topic)), 201
    finally:
        db.close()


def _validate_topic_update_payload(body):
    status = body.get("status")
    weight = body.get("weight")

    if status is None and weight is None:
        return None, None, make_error_response("VALIDATION_ERROR", "Falta status o weight.", 422)

    if status is not None:
        if not isinstance(status, str) or status not in {"pending", "approved", "rejected"}:
            return None, None, make_error_response("VALIDATION_ERROR", f"Estado no válido: {status}", 422)

    weight_val = None
    if weight is not None:
        try:
            weight_val = float(weight)
            if weight_val < 0.0 or weight_val > 10.0:
                raise ValueError()
        except (ValueError, TypeError):
            return None, None, make_error_response("VALIDATION_ERROR", "El peso debe ser un número entre 0 y 10.", 422)

    return status, weight_val, None


@discovery_bp.route("/categories/<int:category_id>/exploration-topics/<int:topic_id>", methods=["PATCH"])
def update_exploration_topic(category_id, topic_id):
    body = request.get_json(silent=True) or {}
    status, weight_val, err_resp = _validate_topic_update_payload(body)
    if err_resp:
        return err_resp

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return make_error_response("NOT_FOUND", "Categoría no encontrada.", 404)

        cursor = db.execute(
            "SELECT id, term FROM category_exploration_topics WHERE id = ? AND category_id = ?",
            (topic_id, category_id),
        )
        row = cursor.fetchone()
        if not row:
            return make_error_response("NOT_FOUND", "Tema no encontrado en esta categoría.", 404)

        if status:
            ExplorationTopicService.update_topic_status(db, topic_id, status)
        if weight_val is not None:
            db.execute("UPDATE category_exploration_topics SET weight = ? WHERE id = ?", (weight_val, topic_id))

        db.commit()

        cursor = db.execute("SELECT * FROM category_exploration_topics WHERE id = ?", (topic_id,))
        topic = dict(cursor.fetchone())
        return jsonify(serialize_exploration_topic(topic))
    finally:
        db.close()


@discovery_bp.route("/channels/<int:channel_id>/suggest-follow", methods=["GET"])
def suggest_follow_channel(channel_id):
    cat_id_raw = request.args.get("categoryId")
    if not cat_id_raw:
        return make_error_response("VALIDATION_ERROR", "Falta categoryId.", 400)

    try:
        category_id = int(cat_id_raw)
    except (ValueError, TypeError):
        return make_error_response("VALIDATION_ERROR", "categoryId debe ser un entero.", 400)

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        chan_check = db.execute("SELECT 1 FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if not chan_check:
            return make_error_response("NOT_FOUND", "Canal no encontrado.", 404)

        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return make_error_response("NOT_FOUND", "Categoría no encontrada.", 404)

        count = DiscoveryRepository.get_channel_positive_videos_count(db, category_id, channel_id)
        suggest_threshold = current_app.config.get("DISCOVERY_SUGGEST_CHANNEL_THRESHOLD_VIDEOS", 2)
        suggest = count >= suggest_threshold
        return jsonify({
            "channelId": channel_id,
            "categoryId": category_id,
            "positiveVideosCount": count,
            "suggestFollow": suggest,
        })
    finally:
        db.close()
