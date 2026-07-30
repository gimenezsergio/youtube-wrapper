from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.db import get_db

videos_bp = Blueprint("videos", __name__)


def _serialize_channel(row, category_ids=None):
    return {
        "id": row["channel_id"],
        "youtubeChannelId": row["channel_youtube_channel_id"],
        "title": row["channel_title"],
        "description": row["channel_description"],
        "thumbnailUrl": row["channel_thumbnail_url"],
        "subscribed": bool(row["channel_is_subscribed"]),
        "locallyFollowed": bool(row["channel_is_locally_followed"]),
        "blocked": bool(row["channel_is_blocked"]),
        "categoryIds": category_ids or []
    }


def _serialize_video(row, discovery_contexts=None, category_ids=None):
    channel = _serialize_channel(row, category_ids)

    # Determinar origin
    is_followed = row["channel_is_subscribed"] or row["channel_is_locally_followed"]
    origin = "followed" if is_followed else "discovery"

    return {
        "id": row["id"],
        "youtubeVideoId": row["youtube_video_id"],
        "channel": channel,
        "title": row["title"],
        "description": row["description"],
        "publishedAt": row["published_at"],
        "durationSeconds": row["duration_seconds"],
        "thumbnailUrl": row["thumbnail_url"],
        "contentType": row["content_type"],
        "origin": origin,
        "watched": bool(row["video_watched"]),
        "discoveryContexts": discovery_contexts or []
    }


def _build_where_clause(category_id, channel_ids_str, watched, origin):
    """Construye las cláusulas WHERE y los parámetros para la consulta de videos."""
    where_clauses = ["c.is_blocked = 0"]
    params = []

    # Excluir videos ocultados por feedback
    where_clauses.append(
        "v.id NOT IN (SELECT video_id FROM discovery_feedback WHERE action = 'hide_video' AND video_id IS NOT NULL)"
    )

    # Filtro de origen general (seguidos o candidatos de descubrimiento)
    where_clauses.append("""
        (c.is_subscribed = 1
         OR c.is_locally_followed = 1
         OR v.id IN (SELECT video_id FROM discovery_candidates))
    """)

    # Filtro por categoría
    if category_id is not None:
        where_clauses.append("""
            (c.id IN (SELECT channel_id FROM channel_categories WHERE category_id = ?)
             OR v.id IN (SELECT video_id FROM discovery_candidates WHERE category_id = ?))
        """)
        params.extend([category_id, category_id])

    # Filtro por lista de canales
    if channel_ids_str:
        try:
            chan_ids = [int(i.strip()) for i in channel_ids_str.split(",") if i.strip()]
            if chan_ids:
                placeholders = ",".join("?" for _ in chan_ids)
                where_clauses.append(f"v.channel_id IN ({placeholders})")
                params.extend(chan_ids)
        except ValueError:
            return None, None, ("channelIds debe ser una lista de enteros separados por coma.", 400)

    # Filtro por visto / no visto
    if watched == "true":
        where_clauses.append("COALESCE(vus.watched, 0) = 1")
    elif watched == "false":
        where_clauses.append("COALESCE(vus.watched, 0) = 0")

    # Filtro por procedencia
    if origin == "followed":
        where_clauses.append("(c.is_subscribed = 1 OR c.is_locally_followed = 1)")
    elif origin == "discovery":
        where_clauses.append("""
            (v.id IN (SELECT video_id FROM discovery_candidates)
             AND NOT (c.is_subscribed = 1 OR c.is_locally_followed = 1))
        """)

    return " AND ".join(where_clauses), params, None


def _list_feed_view(db, where_sql, params, cursor, limit):
    """Obtiene y serializa videos para la vista feed."""
    cursor_clauses = ""
    cursor_params = []
    if cursor:
        try:
            cursor_parts = cursor.split("_", 1)
            if len(cursor_parts) == 2:
                cursor_pub, cursor_id = cursor_parts[0], int(cursor_parts[1])
                cursor_clauses = " AND (v.published_at < ? OR (v.published_at = ? AND v.id < ?))"
                cursor_params.extend([cursor_pub, cursor_pub, cursor_id])
        except ValueError:
            return None, ("Cursor inválido.", 400)

    query_sql = f"""
        SELECT v.*,
               c.youtube_channel_id as channel_youtube_channel_id,
               c.title as channel_title,
               c.description as channel_description,
               c.thumbnail_url as channel_thumbnail_url,
               c.is_subscribed as channel_is_subscribed,
               c.is_locally_followed as channel_is_locally_followed,
               c.is_blocked as channel_is_blocked,
               vus.watched as video_watched,
               vus.opened_at as video_opened_at,
               vus.watched_source as video_watched_source
        FROM videos v
        JOIN channels c ON v.channel_id = c.id
        LEFT JOIN video_user_state vus ON v.id = vus.video_id
        WHERE {where_sql} {cursor_clauses}
        ORDER BY v.published_at DESC, v.id DESC
        LIMIT ?
    """
    all_params = params + cursor_params + [limit]
    cursor_res = db.execute(query_sql, all_params).fetchall()

    video_ids = [row["id"] for row in cursor_res]
    channel_ids = list({row["channel_id"] for row in cursor_res})

    discovery_map = {}
    if video_ids:
        placeholders = ",".join("?" for _ in video_ids)
        disc_rows = db.execute(f"""
            SELECT video_id, category_id, score, reasons_json
            FROM discovery_candidates
            WHERE video_id IN ({placeholders})
        """, video_ids).fetchall()
        for r in disc_rows:
            disc_info = {
                "categoryId": r["category_id"],
                "score": r["score"],
                "reasons": r["reasons_json"]
            }
            discovery_map.setdefault(r["video_id"], []).append(disc_info)

    category_map = {}
    if channel_ids:
        placeholders = ",".join("?" for _ in channel_ids)
        cat_rows = db.execute(f"""
            SELECT channel_id, category_id
            FROM channel_categories
            WHERE channel_id IN ({placeholders})
        """, channel_ids).fetchall()
        for r in cat_rows:
            category_map.setdefault(r["channel_id"], []).append(r["category_id"])

    items = []
    for row in cursor_res:
        items.append(_serialize_video(
            row,
            discovery_contexts=discovery_map.get(row["id"]),
            category_ids=category_map.get(row["channel_id"])
        ))

    next_cursor = None
    if len(items) == limit:
        last_item = cursor_res[-1]
        next_cursor = f"{last_item['published_at']}_{last_item['id']}"

    return {
        "view": "feed",
        "items": items,
        "nextCursor": next_cursor
    }, None


def _fetch_channel_metadata(db, page_channel_ids, placeholders):
    """Obtiene metadatos de los canales en la página actual."""
    channels_details_rows = db.execute(f"""
        SELECT id as channel_id,
               youtube_channel_id as channel_youtube_channel_id,
               title as channel_title,
               description as channel_description,
               thumbnail_url as channel_thumbnail_url,
               is_subscribed as channel_is_subscribed,
               is_locally_followed as channel_is_locally_followed,
               is_blocked as channel_is_blocked
        FROM channels
        WHERE id IN ({placeholders})
    """, page_channel_ids).fetchall()

    category_map = {}
    cat_rows = db.execute(f"""
        SELECT channel_id, category_id
        FROM channel_categories
        WHERE channel_id IN ({placeholders})
    """, page_channel_ids).fetchall()
    for r in cat_rows:
        category_map.setdefault(r["channel_id"], []).append(r["category_id"])

    channels_detail_map = {
        r["channel_id"]: _serialize_channel(r, category_map.get(r["channel_id"]))
        for r in channels_details_rows
    }
    return channels_detail_map, category_map


def _fetch_channel_videos(db, page_channel_ids, placeholders, where_sql, params, category_map):
    """Obtiene y agrupa videos para cada canal."""
    videos_query_filtered = f"""
        WITH ranked_videos AS (
            SELECT v.*,
                   c.youtube_channel_id as channel_youtube_channel_id,
                   c.title as channel_title,
                   c.description as channel_description,
                   c.thumbnail_url as channel_thumbnail_url,
                   c.is_subscribed as channel_is_subscribed,
                   c.is_locally_followed as channel_is_locally_followed,
                   c.is_blocked as channel_is_blocked,
                   vus.watched as video_watched,
                   vus.opened_at as video_opened_at,
                   vus.watched_source as video_watched_source,
                   ROW_NUMBER() OVER (PARTITION BY v.channel_id ORDER BY v.published_at DESC, v.id DESC) as rn
            FROM videos v
            JOIN channels c ON v.channel_id = c.id
            LEFT JOIN video_user_state vus ON v.id = vus.video_id
            WHERE v.channel_id IN ({placeholders}) AND {where_sql}
        )
        SELECT * FROM ranked_videos WHERE rn <= 10
        ORDER BY published_at DESC, id DESC
    """
    videos_params = page_channel_ids + params
    videos_rows = db.execute(videos_query_filtered, videos_params).fetchall()

    video_ids = [row["id"] for row in videos_rows]
    discovery_map = {}
    if video_ids:
        placeholders_v = ",".join("?" for _ in video_ids)
        disc_rows = db.execute(f"""
            SELECT video_id, category_id, score, reasons_json
            FROM discovery_candidates
            WHERE video_id IN ({placeholders_v})
        """, video_ids).fetchall()
        for r in disc_rows:
            disc_info = {
                "categoryId": r["category_id"],
                "score": r["score"],
                "reasons": r["reasons_json"]
            }
            discovery_map.setdefault(r["video_id"], []).append(disc_info)

    channel_videos = {}
    for r in videos_rows:
        channel_videos.setdefault(r["channel_id"], []).append(
            _serialize_video(
                r,
                discovery_contexts=discovery_map.get(r["id"]),
                category_ids=category_map.get(r["channel_id"])
            )
        )
    return channel_videos


def _list_channels_view(db, where_sql, params, cursor, limit):
    """Obtiene y agrupa videos por canal para la vista agrupada."""
    cursor_clauses = ""
    cursor_params = []
    if cursor:
        try:
            cursor_parts = cursor.split("_", 1)
            if len(cursor_parts) == 2:
                cursor_date, cursor_chan_id = cursor_parts[0], int(cursor_parts[1])
                cursor_clauses = " HAVING (latest_video_date < ? OR (latest_video_date = ? AND v.channel_id < ?))"
                cursor_params.extend([cursor_date, cursor_date, cursor_chan_id])
        except ValueError:
            return None, ("Cursor inválido.", 400)

    channels_query = f"""
        SELECT v.channel_id, MAX(v.published_at) as latest_video_date
        FROM videos v
        JOIN channels c ON v.channel_id = c.id
        LEFT JOIN video_user_state vus ON v.id = vus.video_id
        WHERE {where_sql}
        GROUP BY v.channel_id
        {cursor_clauses}
        ORDER BY latest_video_date DESC, v.channel_id DESC
        LIMIT ?
    """
    channels_params = params + cursor_params + [limit]
    chan_rows = db.execute(channels_query, channels_params).fetchall()

    if not chan_rows:
        return {
            "view": "channels",
            "items": [],
            "nextCursor": None
        }, None

    page_channel_ids = [r["channel_id"] for r in chan_rows]
    placeholders = ",".join("?" for _ in page_channel_ids)

    channels_detail_map, category_map = _fetch_channel_metadata(db, page_channel_ids, placeholders)
    channel_videos = _fetch_channel_videos(
        db, page_channel_ids, placeholders, where_sql, params, category_map
    )

    # Construir respuesta respetando el orden de canales paginados
    items = []
    for chan_row in chan_rows:
        chan_id = chan_row["channel_id"]
        if chan_id in channels_detail_map:
            items.append({
                "channel": channels_detail_map[chan_id],
                "videos": channel_videos.get(chan_id, [])
            })

    next_cursor = None
    if len(chan_rows) == limit:
        last_chan = chan_rows[-1]
        next_cursor = f"{last_chan['latest_video_date']}_{last_chan['channel_id']}"

    return {
        "view": "channels",
        "items": items,
        "nextCursor": next_cursor
    }, None


@videos_bp.route("/videos", methods=["GET"])
def list_videos():
    """Listar videos filtrados con paginación por cursor (Feed o Por canal)."""
    db = get_db()

    # Obtener parámetros de consulta
    category_id = request.args.get("categoryId", type=int)
    channel_ids_str = request.args.get("channelIds", type=str)
    watched = request.args.get("watched", default="all", type=str)
    origin = request.args.get("origin", default="all", type=str)
    view = request.args.get("view", default="feed", type=str)
    cursor = request.args.get("cursor", type=str)
    limit = min(request.args.get("limit", default=30, type=int), 100)

    # Validar parámetros
    if watched not in ["all", "true", "false"]:
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "watched debe ser all, true o false."
            }
        }), 400
    if origin not in ["all", "followed", "discovery"]:
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "origin debe ser all, followed o discovery."
            }
        }), 400
    if view not in ["feed", "channels"]:
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "view debe ser feed o channels."
            }
        }), 400

    # Construir cláusula WHERE
    where_sql, params, err = _build_where_clause(category_id, channel_ids_str, watched, origin)
    if err:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": err[0]}}), err[1]

    if view == "feed":
        res, err_cursor = _list_feed_view(db, where_sql, params, cursor, limit)
        if err_cursor:
            return jsonify({"error": {"code": "VALIDATION_ERROR", "message": err_cursor[0]}}), err_cursor[1]
        return jsonify(res), 200
    else:
        res, err_cursor = _list_channels_view(db, where_sql, params, cursor, limit)
        if err_cursor:
            return jsonify({"error": {"code": "VALIDATION_ERROR", "message": err_cursor[0]}}), err_cursor[1]
        return jsonify(res), 200


@videos_bp.route("/videos/<int:video_id>/open", methods=["POST"])
def open_video(video_id):
    """Registra la apertura de un video y retorna su URL de YouTube."""
    db = get_db()

    # Comprobar que el video existe
    cursor = db.execute("SELECT youtube_video_id FROM videos WHERE id = ?", (video_id,))
    row = cursor.fetchone()
    if not row:
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Video no encontrado."}}), 404

    yt_video_id = row["youtube_video_id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        # Registrar o actualizar el estado visto
        db.execute("""
            INSERT INTO video_user_state (video_id, opened_at, open_count, watched, watched_source, updated_at)
            VALUES (?, ?, 1, 1, 'opened', ?)
            ON CONFLICT(video_id) DO UPDATE SET
                opened_at = ?,
                open_count = open_count + 1,
                watched = 1,
                watched_source = 'opened',
                updated_at = ?
        """, (video_id, now_iso, now_iso, now_iso, now_iso))
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": {"code": "DATABASE_ERROR", "message": f"Error de persistencia: {e}"}}), 500

    youtube_url = f"https://www.youtube.com/watch?v={yt_video_id}"
    return jsonify({
        "url": youtube_url,
        "watched": True,
        "openedAt": now_iso
    }), 200


@videos_bp.route("/videos/<int:video_id>/watched", methods=["PUT"])
def set_watched(video_id):
    """Marcar manualmente un video como visto o no visto."""
    data = request.get_json(silent=True) or {}
    watched = data.get("watched")

    if watched is None or not isinstance(watched, bool):
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Es necesario indicar boolean 'watched'."
            }
        }), 422

    db = get_db()

    # Comprobar que el video existe
    cursor = db.execute("SELECT id FROM videos WHERE id = ?", (video_id,))
    if not cursor.fetchone():
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Video no encontrado."}}), 404

    now_iso = datetime.now(timezone.utc).isoformat()
    watched_val = 1 if watched else 0

    try:
        db.execute("""
            INSERT INTO video_user_state (video_id, opened_at, open_count, watched, watched_source, updated_at)
            VALUES (?, NULL, 0, ?, 'manual', ?)
            ON CONFLICT(video_id) DO UPDATE SET
                watched = ?,
                watched_source = 'manual',
                updated_at = ?
        """, (video_id, watched_val, now_iso, watched_val, now_iso))
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": {"code": "DATABASE_ERROR", "message": f"Error al guardar estado visto: {e}"}}), 500

    # Obtener el registro de estado final
    cursor = db.execute("SELECT opened_at, watched_source FROM video_user_state WHERE video_id = ?", (video_id,))
    state_row = cursor.fetchone()

    return jsonify({
        "videoId": video_id,
        "watched": watched,
        "openedAt": state_row["opened_at"],
        "source": state_row["watched_source"]
    }), 200
