from flask import Blueprint, jsonify, request

from app.db import get_db

channels_bp = Blueprint("channels", __name__)

def _serialize_channel(row):
    """Convierte una fila de SQLite en el esquema JSON de Channel."""
    cat_ids_str = row["category_ids"]
    category_ids = [int(x) for x in cat_ids_str.split(",")] if cat_ids_str else []

    return {
        "id": row["id"],
        "youtubeChannelId": row["youtube_channel_id"],
        "title": row["title"],
        "description": row["description"] or "",
        "thumbnailUrl": row["thumbnail_url"] or "",
        "subscribed": bool(row["is_subscribed"]),
        "locallyFollowed": bool(row["is_locally_followed"]),
        "blocked": bool(row["is_blocked"]),
        "categoryIds": category_ids
    }

@channels_bp.route("/channels", methods=["GET"])
def list_channels():
    """Listar canales paginados con soporte de filtros (suscritos, query, categoría, sin clasificar)."""
    category_id = request.args.get("categoryId", type=int)
    unclassified = request.args.get("unclassified") # "true" o "false"
    subscribed = request.args.get("subscribed") # "true" o "false"
    query_param = request.args.get("query")
    cursor = request.args.get("cursor")
    limit = request.args.get("limit", default=30, type=int)

    db = get_db()

    # Construcción dinámica de la query
    sql_base = """
        SELECT c.*, GROUP_CONCAT(cc.category_id) as category_ids
        FROM channels c
        LEFT JOIN channel_categories cc ON c.id = cc.channel_id
    """

    where_clauses = []
    params = []

    # Filtro de cursor (cursor-based pagination por ID incremental)
    if cursor:
        try:
            cursor_id = int(cursor)
            where_clauses.append("c.id > ?")
            params.append(cursor_id)
        except ValueError:
            return jsonify({"error": {"code": "INVALID_CURSOR", "message": "El cursor provisto no es válido."}}), 400

    # Filtro por suscripción a YouTube
    if subscribed == "true":
        where_clauses.append("c.is_subscribed = 1")
    elif subscribed == "false":
        where_clauses.append("c.is_subscribed = 0")

    # Filtro por búsqueda de texto
    if query_param and query_param.strip():
        where_clauses.append("c.title LIKE ?")
        params.append(f"%{query_param.strip()}%")

    # Filtro por categoría específica
    if category_id is not None:
        where_clauses.append("c.id IN (SELECT channel_id FROM channel_categories WHERE category_id = ?)")
        params.append(category_id)

    # Filtro por "sin clasificar" (no tiene categorías)
    if unclassified == "true":
        where_clauses.append("c.id NOT IN (SELECT channel_id FROM channel_categories)")

    # Unir cláusulas WHERE
    if where_clauses:
        sql_base += " WHERE " + " AND ".join(where_clauses)

    # Agrupamiento por ID
    sql_base += " GROUP BY c.id ORDER BY c.id ASC LIMIT ?"
    params.append(limit + 1)  # Pedir 1 extra para determinar si hay página siguiente

    cursor_db = db.execute(sql_base, params)
    rows = cursor_db.fetchall()

    has_next = len(rows) > limit
    results = rows[:limit]

    items = [_serialize_channel(r) for r in results]
    next_cursor = str(items[-1]["id"]) if has_next and items else None

    return jsonify({
        "items": items,
        "nextCursor": next_cursor
    }), 200

@channels_bp.route("/channels/<int:channel_id>", methods=["GET"])
def get_channel(channel_id):
    """Obtener los detalles de un canal."""
    db = get_db()
    cursor = db.execute("""
        SELECT c.*, GROUP_CONCAT(cc.category_id) as category_ids
        FROM channels c
        LEFT JOIN channel_categories cc ON c.id = cc.channel_id
        WHERE c.id = ?
        GROUP BY c.id
    """, (channel_id,))
    row = cursor.fetchone()
    if not row:
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Canal no encontrado."}}), 404

    return jsonify(_serialize_channel(row)), 200

@channels_bp.route("/channels/<int:channel_id>/block", methods=["PUT"])
def set_channel_blocked(channel_id):
    """Bloquear o desbloquear un canal."""
    data = request.get_json(silent=True) or {}
    blocked = data.get("blocked")

    if blocked is None or not isinstance(blocked, bool):
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Es necesario proveer un valor booleano en 'blocked'."
            }
        }), 422

    db = get_db()
    # Verificar si el canal existe
    chk = db.execute("SELECT 1 FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if not chk:
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Canal no encontrado."}}), 404

    db.execute("UPDATE channels SET is_blocked = ? WHERE id = ?", (int(blocked), channel_id))

    if blocked:
        # Retirar todos sus candidatos activos de descubrimiento si se bloquea
        db.execute("""
            UPDATE discovery_candidates
            SET status = 'expired'
            WHERE video_id IN (SELECT id FROM videos WHERE channel_id = ?)
              AND status = 'active'
        """, (channel_id,))

    db.commit()

    # Retornar el canal actualizado
    cursor = db.execute("""
        SELECT c.*, GROUP_CONCAT(cc.category_id) as category_ids
        FROM channels c
        LEFT JOIN channel_categories cc ON c.id = cc.channel_id
        WHERE c.id = ?
        GROUP BY c.id
    """, (channel_id,))
    return jsonify(_serialize_channel(cursor.fetchone())), 200

@channels_bp.route("/channels/<int:channel_id>/categories", methods=["PUT"])
def update_channel_categories(channel_id):
    """Actualiza las categorías de un canal y registra las decisiones manuales."""
    from datetime import datetime, timezone
    data = request.get_json(silent=True) or {}
    category_ids = data.get("categoryIds")

    if category_ids is None or not isinstance(category_ids, list):
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Es necesario proveer una lista de IDs en 'categoryIds'."
            }
        }), 422

    # Validar que todos los IDs sean enteros
    for cid in category_ids:
        if not isinstance(cid, int):
            return jsonify({
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Todos los IDs de categorías deben ser enteros."
                }
            }), 422

    db = get_db()

    # Verificar si el canal existe
    cursor = db.execute("SELECT id FROM channels WHERE id = ?", (channel_id,))
    if not cursor.fetchone():
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Canal no encontrado."}}), 404

    # Validar existencia de categorías
    if category_ids:
        placeholders = ",".join("?" for _ in category_ids)
        cursor = db.execute(f"SELECT COUNT(*) as count FROM categories WHERE id IN ({placeholders})", category_ids)
        if cursor.fetchone()["count"] != len(set(category_ids)):
            return jsonify({
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Una o más categorías provistas no existen."
                }
            }), 400

    # Obtener categorías actuales
    cursor = db.execute("SELECT category_id FROM channel_categories WHERE channel_id = ?", (channel_id,))
    old_ids = {row["category_id"] for row in cursor.fetchall()}
    new_ids = set(category_ids)

    added_ids = new_ids - old_ids
    removed_ids = old_ids - new_ids
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        # 1. Procesar categorías agregadas
        for cat_id in added_ids:
            db.execute("""
                INSERT INTO channel_categories (channel_id, category_id, source, created_at)
                VALUES (?, ?, 'manual', ?)
            """, (channel_id, cat_id, now_iso))

            db.execute("""
                INSERT INTO classification_decisions (channel_id, category_id, decision, updated_at)
                VALUES (?, ?, 'include', ?)
                ON CONFLICT(channel_id, category_id) DO UPDATE
                SET decision = excluded.decision, updated_at = excluded.updated_at
            """, (channel_id, cat_id, now_iso))

        # 2. Procesar categorías eliminadas
        for cat_id in removed_ids:
            db.execute("""
                DELETE FROM channel_categories
                WHERE channel_id = ? AND category_id = ?
            """, (channel_id, cat_id))

            db.execute("""
                INSERT INTO classification_decisions (channel_id, category_id, decision, updated_at)
                VALUES (?, ?, 'exclude', ?)
                ON CONFLICT(channel_id, category_id) DO UPDATE
                SET decision = excluded.decision, updated_at = excluded.updated_at
            """, (channel_id, cat_id, now_iso))

        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": f"Fallo al actualizar categorías en base de datos: {e}"
            }
        }), 500

    # Retornar el canal actualizado
    cursor = db.execute("""
        SELECT c.*, GROUP_CONCAT(cc.category_id) as category_ids
        FROM channels c
        LEFT JOIN channel_categories cc ON c.id = cc.channel_id
        WHERE c.id = ?
        GROUP BY c.id
    """, (channel_id,))
    return jsonify(_serialize_channel(cursor.fetchone())), 200

@channels_bp.route("/channels/sync", methods=["POST"])
def sync_channels():
    """Sincronizar suscripciones y videos desde la API de YouTube."""
    from app.services.subscription_service import SubscriptionService
    from app.services.video_service import VideoService
    db = get_db()
    try:
        sub_service = SubscriptionService()
        sub_result = sub_service.sync_subscriptions(db)

        video_service = VideoService()
        video_result = video_service.sync_videos(db)

        result = {
            "created": sub_result["created"],
            "updated": sub_result["updated"],
            "unsubscribed": sub_result["unsubscribed"],
            "videos_created": video_result["created"],
            "videos_updated": video_result["updated"],
            "processed_channels": video_result["processed_channels"]
        }
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            "error": {
                "code": "SYNC_FAILED",
                "message": f"Fallo al sincronizar suscripciones y videos: {e}"
            }
        }), 500

