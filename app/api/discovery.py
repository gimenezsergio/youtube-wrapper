import json

from flask import Blueprint, current_app, jsonify, request

from app.db import get_db_connection
from app.domain.discovery.normalization import normalize_term
from app.repositories.discovery_repository import DiscoveryRepository
from app.repositories.exploration_topic_repository import ExplorationTopicRepository
from app.repositories.refresh_run_repository import RefreshRunRepository
from app.services.exploration_topic_service import ExplorationTopicService

discovery_bp = Blueprint("discovery", __name__)

def serialize_refresh_run(run_dict):
    if not run_dict:
        return None
    stages = []
    if run_dict.get("requested_stages_json"):
        try:
            stages = json.loads(run_dict["requested_stages_json"])
        except Exception:
            stages = []

    counters = {}
    if run_dict.get("counters_json"):
        try:
            counters = json.loads(run_dict["counters_json"])
        except Exception:
            counters = {}

    errors_raw = {}
    if run_dict.get("errors_json"):
        try:
            errors_raw = json.loads(run_dict["errors_json"])
        except Exception:
            errors_raw = {}

    errors = []
    if isinstance(errors_raw, dict):
        for k, v in errors_raw.items():
            errors.append({"stage": k, "message": str(v)})
    elif isinstance(errors_raw, list):
        errors = errors_raw

    return {
        "id": run_dict["id"],
        "status": run_dict["status"],
        "currentStage": run_dict.get("current_stage"),
        "stages": stages,
        "requestedAt": run_dict.get("requested_at"),
        "startedAt": run_dict.get("started_at"),
        "finishedAt": run_dict.get("finished_at"),
        "counters": counters,
        "errors": errors,
        "heartbeatAt": run_dict.get("heartbeat_at"),
        "leaseExpiresAt": run_dict.get("lease_expires_at")
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
        "categoryIds": cat_ids
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
        "watched": bool(r_dict.get("watched", 0))
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
        "updatedAt": topic_dict["updated_at"]
    }

@discovery_bp.route("/discoveries", methods=["GET"])
def list_discoveries():
    cat_id_raw = request.args.get("categoryId")
    band = request.args.get("band", default="all")
    offset = request.args.get("cursor", default="0")
    limit_raw = request.args.get("limit", default="25")

    # 1. Validar cursor
    try:
        offset_int = int(offset)
        if offset_int < 0:
            raise ValueError()
    except ValueError:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "El parámetro cursor debe ser un entero no negativo."}}), 400

    # 2. Validar band
    valid_bands = {"all", "related", "adjacent", "exploratory"}
    if band not in valid_bands:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": f"Banda no válida: {band}"}}), 400

    # 3. Validar limit
    try:
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            raise ValueError()
    except ValueError:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "El parámetro limit debe ser un entero entre 1 y 100."}}), 400

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        # 4. Validar categoryId si está presente
        if cat_id_raw is not None:
            try:
                cat_id = int(cat_id_raw)
            except ValueError:
                return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "categoryId debe ser un entero."}}), 400

            cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (cat_id,)).fetchone()
            if not cat_check:
                return jsonify({"error": {"code": "NOT_FOUND", "message": "Categoría no encontrada."}}), 404
        else:
            cat_id = None

        recs, batches, next_cursor = DiscoveryRepository.get_active_batch_recommendations(
            db, category_id=cat_id, band=band, offset=offset_int, limit=limit
        )
        return jsonify({
            "items": recs,
            "batches": batches,
            "nextCursor": next_cursor
        })
    finally:
        db.close()

@discovery_bp.route("/discoveries/<int:video_id>/feedback", methods=["POST"])
def submit_discovery_feedback(video_id):
    body = request.get_json() or {}
    category_id = body.get("categoryId")
    action = body.get("action")

    if not category_id or not action:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "Falta categoryId o action"}}), 400

    valid_actions = {"more_like_this", "less_like_this", "hide_video", "block_channel", "accept_channel"}
    if action not in valid_actions:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": f"Acción no válida: {action}"}}), 400

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        # 1. Validar categoría
        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Categoría no encontrada."}}), 404

        # 2. Validar candidato y derivar channel_id
        candidate = db.execute("""
            SELECT v.channel_id FROM discovery_candidates dc
            JOIN videos v ON dc.video_id = v.id
            WHERE dc.video_id = ? AND dc.category_id = ?
        """, (video_id, category_id)).fetchone()
        if not candidate:
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Candidato de descubrimiento no encontrado para esta categoría."}}), 404

        channel_id = candidate["channel_id"]

        DiscoveryRepository.save_feedback(db, video_id=video_id, channel_id=channel_id, category_id=category_id, action=action)
        db.commit()
        return jsonify({"applied": True})
    finally:
        db.close()

@discovery_bp.route("/discoveries/<int:video_id>/hidden", methods=["DELETE"])
def restore_hidden_discovery(video_id):
    category_id = request.args.get("categoryId", type=int)
    if not category_id:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "Falta categoryId"}}), 400

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        # 1. Validar categoría
        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Categoría no encontrada."}}), 404

        # 2. Validar candidato ocultado
        candidate_check = db.execute("""
            SELECT 1 FROM discovery_candidates
            WHERE video_id = ? AND category_id = ? AND status = 'hidden'
        """, (video_id, category_id)).fetchone()
        if not candidate_check:
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Candidato oculto no encontrado para esta categoría."}}), 404

        # Revertir ocultación: eliminar el feedback 'hide_video' de la categoría
        # y poner el candidato de vuelta en 'active'
        db.execute("""
            DELETE FROM discovery_feedback
            WHERE video_id = ? AND category_id = ? AND action = 'hide_video'
        """, (video_id, category_id))

        db.execute("""
            UPDATE discovery_candidates
            SET status = 'active'
            WHERE video_id = ? AND category_id = ? AND status = 'hidden'
        """, (video_id, category_id))

        db.commit()
        return "", 204
    finally:
        db.close()

@discovery_bp.route("/settings/discovery-exclusions", methods=["GET"])
def list_discovery_exclusions():
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        # 1. Canales bloqueados
        cursor = db.execute("""
            SELECT c.*, GROUP_CONCAT(cc.category_id) as category_ids
            FROM channels c
            LEFT JOIN channel_categories cc ON c.id = cc.channel_id
            WHERE c.is_blocked = 1
            GROUP BY c.id
        """)
        blocked_channels = [_serialize_channel(dict(row)) for row in cursor.fetchall()]

        # 2. Videos ocultos
        cursor = db.execute("""
            SELECT
                v.id, v.youtube_video_id, v.title, v.description, v.published_at, v.duration_seconds, v.thumbnail_url, v.content_type,
                ch.id as channel_id, ch.youtube_channel_id, ch.title as channel_title, ch.description as channel_description,
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
                "is_blocked": row["is_blocked"]
            }
            cat_assigned = db.execute("SELECT category_id FROM channel_categories WHERE channel_id = ?", (row["channel_id"],)).fetchall()
            cat_ids = [r["category_id"] for r in cat_assigned]

            video_obj = _serialize_video(row, channel_row, cat_ids)
            hidden_videos.append({
                "video": video_obj,
                "categoryId": row["category_id"],
                "hiddenAt": row["hidden_at"]
            })

        return jsonify({
            "blockedChannels": blocked_channels,
            "hiddenVideos": hidden_videos
        })
    finally:
        db.close()

@discovery_bp.route("/refresh-runs", methods=["GET"])
def list_refresh_runs():
    limit_raw = request.args.get("limit", default="30")
    try:
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            raise ValueError()
    except ValueError:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "El parámetro limit debe ser un entero entre 1 y 100."}}), 400

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        runs = RefreshRunRepository.list_all(db, limit=limit)
        return jsonify({"items": [serialize_refresh_run(r) for r in runs]})
    finally:
        db.close()

@discovery_bp.route("/refresh-runs", methods=["POST"])
def start_refresh():
    body = request.get_json() or {}
    stages = body.get("stages") or ["subscriptions", "followed_videos", "discovery"]

    valid_stages = {"subscriptions", "followed_videos", "discovery"}
    for s in stages:
        if s not in valid_stages:
            return jsonify({"error": {"code": "VALIDATION_ERROR", "message": f"Etapa desconocida: {s}"}}), 400

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        if RefreshRunRepository.has_active_run(db):
            return jsonify({"error": {"code": "CONFLICT", "message": "Ya hay una actualización activa en curso."}}), 409

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
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Actualización no encontrada."}}), 404
        return jsonify(serialize_refresh_run(run))
    finally:
        db.close()

@discovery_bp.route("/categories/<int:category_id>/exploration-topics", methods=["GET"])
def list_exploration_topics(category_id):
    status = request.args.get("status", default="all")
    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Categoría no encontrada."}}), 404

        all_topics = ExplorationTopicService.list_topics(db, category_id)
        if status != "all":
            all_topics = [t for t in all_topics if t["status"] == status]
        return jsonify({"items": [serialize_exploration_topic(t) for t in all_topics]})
    finally:
        db.close()

@discovery_bp.route("/categories/<int:category_id>/exploration-topics", methods=["POST"])
def create_exploration_topic(category_id):
    body = request.get_json() or {}
    term = body.get("term")
    weight = body.get("weight", 1.0)

    if not term:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "Falta el término"}}), 400

    try:
        weight = float(weight)
        if weight < 0.0 or weight > 10.0:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "El peso debe ser un número entre 0 y 10."}}), 400

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Categoría no encontrada."}}), 404

        norm = normalize_term(term)
        existing = ExplorationTopicRepository.get_by_category_and_term(db, category_id, norm)
        if existing:
            return jsonify({"error": {"code": "CONFLICT", "message": "El tema ya existe en esta categoría."}}), 409

        ExplorationTopicService.create_manual_topic(db, category_id, term, weight)
        db.commit()
        topic = ExplorationTopicRepository.get_by_category_and_term(db, category_id, norm)
        return jsonify(serialize_exploration_topic(topic)), 201
    finally:
        db.close()

@discovery_bp.route("/categories/<int:category_id>/exploration-topics/<int:topic_id>", methods=["PATCH"])
def update_exploration_topic(category_id, topic_id):
    body = request.get_json() or {}
    status = body.get("status")
    weight = body.get("weight")

    if status is None and weight is None:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "Falta status o weight"}}), 400

    if status is not None:
        if status not in {"pending", "approved", "rejected"}:
            return jsonify({"error": {"code": "VALIDATION_ERROR", "message": f"Estado no válido: {status}"}}), 400

    if weight is not None:
        try:
            weight = float(weight)
            if weight < 0.0 or weight > 10.0:
                raise ValueError()
        except (ValueError, TypeError):
            return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "El peso debe ser un número entre 0 y 10."}}), 400

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Categoría no encontrada."}}), 404

        cursor = db.execute("SELECT id, term FROM category_exploration_topics WHERE id = ? AND category_id = ?", (topic_id, category_id))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Tema no encontrado en esta categoría."}}), 404

        if status:
            ExplorationTopicService.update_topic_status(db, topic_id, status)
        if weight is not None:
            db.execute("UPDATE category_exploration_topics SET weight = ? WHERE id = ?", (weight, topic_id))

        db.commit()

        cursor = db.execute("SELECT * FROM category_exploration_topics WHERE id = ?", (topic_id,))
        topic = dict(cursor.fetchone())
        return jsonify(serialize_exploration_topic(topic))
    finally:
        db.close()

@discovery_bp.route("/channels/<int:channel_id>/suggest-follow", methods=["GET"])
def suggest_follow_channel(channel_id):
    category_id = request.args.get("categoryId", type=int)
    if not category_id:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": "Falta categoryId"}}), 400

    db = get_db_connection(current_app.config["DATABASE_PATH"])
    try:
        # 1. Validar existencia de canal
        chan_check = db.execute("SELECT 1 FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if not chan_check:
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Canal no encontrado."}}), 404

        # 2. Validar existencia de categoría
        cat_check = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_check:
            return jsonify({"error": {"code": "NOT_FOUND", "message": "Categoría no encontrada."}}), 404

        count = DiscoveryRepository.get_channel_positive_videos_count(db, category_id, channel_id)
        suggest_threshold = current_app.config.get("DISCOVERY_SUGGEST_CHANNEL_THRESHOLD_VIDEOS", 2)
        suggest = count >= suggest_threshold
        return jsonify({
            "channelId": channel_id,
            "categoryId": category_id,
            "positiveVideosCount": count,
            "suggestFollow": suggest
        })
    finally:
        db.close()
