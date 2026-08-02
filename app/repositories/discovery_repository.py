import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.domain.discovery.models import Band, DiscoveryCandidateDomain, LocalSignal, SignalType
from app.domain.discovery.signals import CategorySignals


class DiscoveryRepository:
    @staticmethod
    def get_blocked_channels(db) -> Set[int]:
        """Obtiene el conjunto de IDs de canales bloqueados globalmente."""
        cursor = db.execute("SELECT id FROM channels WHERE is_blocked = 1")
        return {row["id"] for row in cursor.fetchall()}

    @staticmethod
    def get_hidden_videos(db, category_id: int) -> Set[str]:
        """Obtiene el conjunto de IDs de YouTube de videos ocultados en la categoría."""
        # Se buscan en discovery_feedback con acción 'hide_video' o discovery_candidates con status = 'hidden'
        cursor = db.execute("""
            SELECT v.youtube_video_id
            FROM discovery_feedback df
            JOIN videos v ON df.video_id = v.id
            WHERE df.category_id = ? AND df.action = 'hide_video'
            UNION
            SELECT v.youtube_video_id
            FROM discovery_candidates dc
            JOIN videos v ON dc.video_id = v.id
            WHERE dc.category_id = ? AND dc.status = 'hidden'
        """, (category_id, category_id))
        return {row["youtube_video_id"] for row in cursor.fetchall()}

    @staticmethod
    def get_category_signals(db, category_id: int, signal_window_days: int = 90) -> CategorySignals:  # noqa: C901
        """
        Agrega todas las señales de la categoría (palabras clave, canales semilla,
        videos vistos/abiertos y feedback) dentro de la ventana de días indicada.
        """
        now = datetime.now(timezone.utc)
        limit_date = (now - timedelta(days=signal_window_days)).isoformat()

        # 1. Palabras clave (positivas y negativas)
        cursor = db.execute("""
            SELECT term, polarity, weight
            FROM category_keywords
            WHERE category_id = ?
        """, (category_id,))
        pos_kws = []
        neg_kws = []
        for row in cursor.fetchall():
            if row["polarity"] == "positive":
                pos_kws.append((row["term"], row["weight"]))
            else:
                neg_kws.append(row["term"])

        # 2. Temas adyacentes / exploración aprobados
        cursor = db.execute("""
            SELECT term, weight
            FROM category_exploration_topics
            WHERE category_id = ? AND status = 'approved'
        """, (category_id,))
        approved_topics = [(row["term"], row["weight"]) for row in cursor.fetchall()]

        # 3. Canales semilla de la categoría (seguidos o clasificados manualmente)
        cursor = db.execute("""
            SELECT c.id, c.title, c.description
            FROM channels c
            JOIN channel_categories cc ON c.id = cc.channel_id
            WHERE cc.category_id = ? AND c.is_blocked = 0 AND (
                c.is_subscribed = 1 OR c.is_locally_followed = 1 OR cc.source = 'manual'
            )
        """, (category_id,))
        seed_ids = set()
        seed_titles = []
        seed_descs = []
        for row in cursor.fetchall():
            seed_ids.add(row["id"])
            if row["title"]:
                seed_titles.append(row["title"])
            if row["description"]:
                seed_descs.append(row["description"])

        # 4. Videos vistos/abiertos recientemente (señales locales positivas diferenciadas)
        cursor = db.execute("""
            SELECT v.id as video_id, v.title, v.channel_id, vus.opened_at, vus.watched, vus.updated_at
            FROM video_user_state vus
            JOIN videos v ON vus.video_id = v.id
            JOIN channel_categories cc ON v.channel_id = cc.channel_id
            WHERE cc.category_id = ? AND (vus.opened_at >= ? OR vus.watched = 1 OR vus.updated_at >= ?)
        """, (category_id, limit_date, limit_date))
        pos_video_titles = []
        pos_channel_ids = set()
        local_signals = []

        for row in cursor.fetchall():
            if row["title"]:
                pos_video_titles.append(row["title"])
            if row["channel_id"]:
                pos_channel_ids.add(row["channel_id"])

            if row["watched"] == 1:
                local_signals.append(LocalSignal(
                    video_id=row["video_id"],
                    channel_id=row["channel_id"],
                    title=row["title"],
                    signal_type=SignalType.WATCHED
                ))
            elif row["opened_at"] and row["opened_at"] >= limit_date:
                local_signals.append(LocalSignal(
                    video_id=row["video_id"],
                    channel_id=row["channel_id"],
                    title=row["title"],
                    signal_type=SignalType.OPENED
                ))

        # 5. Feedback explícito de descubrimiento
        cursor = db.execute("""
            SELECT video_id, channel_id, action
            FROM discovery_feedback
            WHERE category_id = ? AND created_at >= ?
        """, (category_id, limit_date))

        negative_video_ids = set()
        negative_channel_ids = set()
        more_like_this_channel_ids = set()

        for row in cursor.fetchall():
            act = row["action"]
            vid = row["video_id"]
            cid = row["channel_id"]
            if act == "less_like_this" or act == "hide_video":
                if vid:
                    negative_video_ids.add(vid)
                if cid:
                    negative_channel_ids.add(cid)
            elif act == "more_like_this":
                if cid:
                    more_like_this_channel_ids.add(cid)
                v_title = None
                if vid:
                    v_cursor = db.execute("SELECT title, channel_id FROM videos WHERE id = ?", (vid,))
                    v_row = v_cursor.fetchone()
                    if v_row:
                        v_title = v_row["title"]
                        pos_video_titles.append(v_title)
                        pos_channel_ids.add(v_row["channel_id"])
                        if v_row["channel_id"]:
                            more_like_this_channel_ids.add(v_row["channel_id"])
                local_signals.append(LocalSignal(
                    video_id=vid,
                    channel_id=cid,
                    title=v_title,
                    signal_type=SignalType.MORE_LIKE_THIS
                ))

        # 6. Bloqueos globales y ocultaciones
        blocked_channel_ids = DiscoveryRepository.get_blocked_channels(db)

        # Ocultos en la categoría
        hidden_vids_yt = DiscoveryRepository.get_hidden_videos(db, category_id)
        # Convertir youtube_video_ids a IDs de base de datos locales
        hidden_video_ids = set()
        if hidden_vids_yt:
            placeholders = ",".join("?" for _ in hidden_vids_yt)
            v_cursor = db.execute(
                f"SELECT id FROM videos WHERE youtube_video_id IN ({placeholders})",
                list(hidden_vids_yt)
            )
            hidden_video_ids = {row["id"] for row in v_cursor.fetchall()}

        # Canales seguidos globalmente
        cursor_followed = db.execute("SELECT id FROM channels WHERE is_subscribed = 1 OR is_locally_followed = 1")
        followed_channel_ids = {row["id"] for row in cursor_followed.fetchall()}

        # Videos ya vistos
        cursor_watched = db.execute("SELECT video_id FROM video_user_state WHERE watched = 1")
        watched_video_ids = {row["video_id"] for row in cursor_watched.fetchall()}

        return CategorySignals(
            category_id=category_id,
            positive_keywords=pos_kws,
            negative_keywords=neg_kws,
            approved_exploration_topics=approved_topics,
            seed_channel_ids=seed_ids,
            seed_channel_titles=seed_titles,
            seed_channel_descriptions=seed_descs,
            positive_video_titles=pos_video_titles,
            positive_channel_ids=pos_channel_ids,
            negative_video_ids=negative_video_ids,
            negative_channel_ids=negative_channel_ids,
            blocked_channel_ids=blocked_channel_ids,
            hidden_video_ids=hidden_video_ids,
            followed_channel_ids=followed_channel_ids,
            watched_video_ids=watched_video_ids,
            local_signals=local_signals,
            more_like_this_channel_ids=more_like_this_channel_ids
        )

    @staticmethod
    def get_channel_positive_videos_count(db, category_id: int, channel_id: int, signal_window_days: int = 90) -> int:
        """Calcula la fuerza total de señales positivas de un canal para la categoría."""
        now = datetime.now(timezone.utc)
        limit_date = (now - timedelta(days=signal_window_days)).isoformat()

        cursor = db.execute("""
            SELECT
                SUM(
                    CASE
                        WHEN cc.category_id IS NOT NULL AND vus.opened_at >= ? THEN 1
                        ELSE 0
                    END +
                    CASE
                        WHEN cc.category_id IS NOT NULL AND vus.watched = 1 AND vus.updated_at >= ? THEN 1
                        ELSE 0
                    END +
                    CASE
                        WHEN df.id IS NOT NULL THEN 5
                        ELSE 0
                    END
                ) as total_strength
            FROM videos v
            LEFT JOIN video_user_state vus ON v.id = vus.video_id
            LEFT JOIN channel_categories cc ON v.channel_id = cc.channel_id AND cc.category_id = ?
            LEFT JOIN discovery_feedback df ON v.id = df.video_id AND df.category_id = ? AND df.action = 'more_like_this' AND df.created_at >= ?
            WHERE v.channel_id = ?
        """, (limit_date, limit_date, category_id, category_id, limit_date, channel_id))
        row = cursor.fetchone()
        return row["total_strength"] if row and row["total_strength"] is not None else 0

    @staticmethod
    def upsert_channel_and_video(db, channel_data: dict, video_data: dict) -> Tuple[int, int]:
        """
        Inserta o actualiza un canal y un video candidatos de YouTube.
        Retorna la tupla (channel_id, video_id) locales de la base de datos.
        """
        now = datetime.now(timezone.utc).isoformat()

        # 1. Upsert Canal
        c_cursor = db.execute("SELECT id FROM channels WHERE youtube_channel_id = ?", (channel_data["youtube_channel_id"],))
        c_row = c_cursor.fetchone()
        if c_row:
            channel_id = c_row["id"]
            db.execute("""
                UPDATE channels
                SET title = ?, description = COALESCE(?, description), thumbnail_url = COALESCE(?, thumbnail_url), updated_at = ?
                WHERE id = ?
            """, (channel_data["title"], channel_data.get("description"), channel_data.get("thumbnail_url"), now, channel_id))
        else:
            c_ins = db.execute("""
                INSERT INTO channels (
                    youtube_channel_id, title, description, thumbnail_url, is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?)
            """, (channel_data["youtube_channel_id"], channel_data["title"], channel_data.get("description"), channel_data.get("thumbnail_url"), now, now))
            channel_id = c_ins.lastrowid

        # 2. Upsert Video
        v_cursor = db.execute("SELECT id FROM videos WHERE youtube_video_id = ?", (video_data["youtube_video_id"],))
        v_row = v_cursor.fetchone()
        if v_row:
            video_id = v_row["id"]
            db.execute("""
                UPDATE videos
                SET title = ?, description = COALESCE(?, description), duration_seconds = COALESCE(?, duration_seconds),
                    thumbnail_url = COALESCE(?, thumbnail_url), content_type = COALESCE(?, content_type), updated_at = ?
                WHERE id = ?
            """, (video_data["title"], video_data.get("description"), video_data.get("duration_seconds"),
                  video_data.get("thumbnail_url"), video_data.get("content_type"), now, video_id))
        else:
            v_ins = db.execute("""
                INSERT INTO videos (
                    youtube_video_id, channel_id, title, description, published_at, duration_seconds, thumbnail_url, content_type, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (video_data["youtube_video_id"], channel_id, video_data["title"], video_data.get("description"),
                  video_data["published_at"], video_data.get("duration_seconds"), video_data.get("thumbnail_url"),
                  video_data.get("content_type", "video"), now, now))
            video_id = v_ins.lastrowid

        return channel_id, video_id

    @staticmethod
    def save_discovery_candidate(db, candidate: DiscoveryCandidateDomain, refresh_run_id: int):
        """Persiste un candidato en la tabla discovery_candidates."""
        now = datetime.now(timezone.utc).isoformat()
        reasons_str = json.dumps(candidate.reasons)

        # Verificar si ya existe en esta categoría
        cursor = db.execute("""
            SELECT status, first_seen_at FROM discovery_candidates
            WHERE video_id = ? AND category_id = ?
        """, (candidate.video_id, candidate.category_id))
        row = cursor.fetchone()

        if row:
            # Mantener status si es hidden o accepted para no sobrescribir feedback
            status = row["status"]
            if status not in ('hidden', 'accepted'):
                status = 'active'

            db.execute("""
                UPDATE discovery_candidates
                SET score = ?, band = ?, reasons_json = ?, status = ?,
                    last_refresh_run_id = ?, selection_rank = ?, last_seen_at = ?
                WHERE video_id = ? AND category_id = ?
            """, (candidate.score, candidate.band.value, reasons_str, status,
                  refresh_run_id, candidate.selection_rank, now,
                  candidate.video_id, candidate.category_id))
        else:
            db.execute("""
                INSERT INTO discovery_candidates (
                    video_id, category_id, score, band, reasons_json, status,
                    last_refresh_run_id, selection_rank, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
            """, (candidate.video_id, candidate.category_id, candidate.score, candidate.band.value,
                  reasons_str, refresh_run_id, candidate.selection_rank, now, now))

    @staticmethod
    def expire_previous_candidates(db, category_id: int, current_run_id: int):
        """Marca como 'expired' los candidatos de la categoría del lote anterior."""
        db.execute("""
            UPDATE discovery_candidates
            SET status = 'expired'
            WHERE category_id = ?
              AND last_refresh_run_id != ?
              AND status = 'active'
        """, (category_id, current_run_id))

    @staticmethod
    def save_discovery_batch(db, run_id: int, category_id: int, counts_dict: dict, shortfall_reason: Optional[str] = None):
        """Guarda o actualiza el resumen del lote (discovery_batches)."""
        now = datetime.now(timezone.utc).isoformat()

        target_total = counts_dict["targetByBand"]["related"] + counts_dict["targetByBand"]["adjacent"] + counts_dict["targetByBand"]["exploratory"]
        selected_total = counts_dict["selectedByBand"]["related"] + counts_dict["selectedByBand"]["adjacent"] + counts_dict["selectedByBand"]["exploratory"]

        target_by_band_json = json.dumps(counts_dict["targetByBand"])
        selected_by_band_json = json.dumps(counts_dict["selectedByBand"])

        db.execute("""
            INSERT OR REPLACE INTO discovery_batches (
                refresh_run_id, category_id, target_total, selected_total,
                target_by_band_json, selected_by_band_json, shortfall_reason, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, category_id, target_total, selected_total,
              target_by_band_json, selected_by_band_json, shortfall_reason, now))

    @staticmethod
    def save_feedback(db, video_id: Optional[int], channel_id: Optional[int], category_id: int, action: str) -> int:
        """Registra una acción de feedback y aplica los efectos colaterales correspondientes."""
        now = datetime.now(timezone.utc).isoformat()

        # Insertar registro de feedback
        cursor = db.execute("""
            INSERT INTO discovery_feedback (video_id, channel_id, category_id, action, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (video_id, channel_id, category_id, action, now))

        # Efectos colaterales inmediatos
        if action == "block_channel" and channel_id:
            # 1. Bloqueo global: marcar is_blocked = 1 en channels
            db.execute("UPDATE channels SET is_blocked = 1 WHERE id = ?", (channel_id,))
            # 2. Retirar todos sus candidatos activos de discovery_candidates
            db.execute("""
                UPDATE discovery_candidates
                SET status = 'expired'
                WHERE video_id IN (SELECT id FROM videos WHERE channel_id = ?)
                  AND status = 'active'
            """, (channel_id,))

        elif action == "hide_video" and video_id:
            # Ocultar video en esta categoría
            db.execute("""
                UPDATE discovery_candidates
                SET status = 'hidden'
                WHERE video_id = ? AND category_id = ?
            """, (video_id, category_id))

        elif action == "accept_channel" and channel_id:
            # 1. Seguir localmente el canal
            db.execute("UPDATE channels SET is_locally_followed = 1 WHERE id = ?", (channel_id,))
            # 2. Relacionarlo con la categoría con source 'accepted_discovery'
            db.execute("""
                INSERT OR IGNORE INTO channel_categories (channel_id, category_id, source, created_at)
                VALUES (?, ?, 'accepted_discovery', ?)
            """, (channel_id, category_id, now))
            # 3. Marcar los candidatos del canal como aceptados
            db.execute("""
                UPDATE discovery_candidates
                SET status = 'accepted'
                WHERE video_id IN (SELECT id FROM videos WHERE channel_id = ?)
                  AND category_id = ?
            """, (channel_id, category_id))

        return cursor.lastrowid

    @staticmethod
    def get_active_batch_recommendations(  # noqa: C901
        db,
        category_id: Optional[int] = None,
        band: Optional[str] = None,
        offset: int = 0,
        limit: int = 25
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Retorna las recomendaciones activas del lote más reciente, los resúmenes de lote
        y opcionalmente el siguiente cursor (basado en offset para paginación).
        """
        where_parts = ["dc.status = 'active'", "ch.is_blocked = 0"]
        params = []

        if category_id:
            where_parts.append("dc.category_id = ?")
            params.append(category_id)

        if band and band != "all":
            where_parts.append("dc.band = ?")
            params.append(band)

        where_clause = " AND ".join(where_parts)

        # Consulta de items
        query = f"""
            SELECT
                v.id as video_id, v.youtube_video_id, v.title, v.description, v.published_at, v.duration_seconds, v.thumbnail_url, v.content_type,
                ch.id as channel_id, ch.youtube_channel_id, ch.title as channel_title, ch.description as channel_description,
                ch.thumbnail_url as channel_thumbnail_url, ch.is_subscribed, ch.is_locally_followed, ch.is_blocked,
                dc.category_id, dc.band, dc.score, dc.selection_rank, dc.reasons_json,
                COALESCE(vus.watched, 0) as watched
            FROM discovery_candidates dc
            JOIN videos v ON dc.video_id = v.id
            JOIN channels ch ON v.channel_id = ch.id
            LEFT JOIN video_user_state vus ON v.id = vus.video_id
            WHERE {where_clause}
            ORDER BY dc.category_id ASC, dc.selection_rank ASC
            LIMIT ? OFFSET ?
        """
        params_items = params + [limit, offset]
        cursor = db.execute(query, params_items)
        rows = cursor.fetchall()

        # Construir mapa de categoryIds por canal
        channel_ids = list({r["channel_id"] for r in rows})
        category_map = {}
        if channel_ids:
            placeholders = ",".join("?" for _ in channel_ids)
            cat_rows = db.execute(f"""
                SELECT channel_id, category_id
                FROM channel_categories
                WHERE channel_id IN ({placeholders})
            """, channel_ids).fetchall()
            for row in cat_rows:
                category_map.setdefault(row["channel_id"], []).append(row["category_id"])

        recommendations = []
        for r in rows:
            reasons = []
            if r["reasons_json"]:
                try:
                    reasons = json.loads(r["reasons_json"])
                except Exception:
                    pass

            is_followed = bool(r["is_subscribed"]) or bool(r["is_locally_followed"])
            origin = "followed" if is_followed else "discovery"

            recommendations.append({
                "video": {
                    "id": r["video_id"],
                    "youtubeVideoId": r["youtube_video_id"],
                    "title": r["title"],
                    "description": r["description"] or "",
                    "publishedAt": r["published_at"],
                    "durationSeconds": r["duration_seconds"],
                    "thumbnailUrl": r["thumbnail_url"] or None,
                    "contentType": r["content_type"] or "video",
                    "origin": origin,
                    "watched": bool(r["watched"]),
                    "channel": {
                        "id": r["channel_id"],
                        "youtubeChannelId": r["youtube_channel_id"],
                        "title": r["channel_title"],
                        "description": r["channel_description"] or "",
                        "thumbnailUrl": r["channel_thumbnail_url"] or None,
                        "subscribed": bool(r["is_subscribed"]),
                        "locallyFollowed": bool(r["is_locally_followed"]),
                        "blocked": bool(r["is_blocked"]),
                        "categoryIds": category_map.get(r["channel_id"], [])
                    }
                },
                "context": {
                    "categoryId": r["category_id"],
                    "band": r["band"],
                    "label": Band(r["band"]).label,
                    "score": r["score"],
                    "selectionRank": r["selection_rank"],
                    "reasons": reasons
                }
            })

        # Consulta de resúmenes de lote (batches)
        query_batches = """
            SELECT db.category_id, db.refresh_run_id, db.target_total, db.selected_total,
                   db.target_by_band_json, db.selected_by_band_json, db.shortfall_reason, db.generated_at
            FROM discovery_batches db
            JOIN (
                SELECT category_id, MAX(generated_at) as max_gen
                FROM discovery_batches
                GROUP BY category_id
            ) latest ON db.category_id = latest.category_id AND db.generated_at = latest.max_gen
        """
        cursor_batches = db.execute(query_batches)
        batches_rows = cursor_batches.fetchall()

        batches = []
        for b in batches_rows:
            try:
                target_by_band = json.loads(b["target_by_band_json"])
                selected_by_band = json.loads(b["selected_by_band_json"])
            except Exception:
                target_by_band = {"related": 5, "adjacent": 2, "exploratory": 1}
                selected_by_band = {"related": 0, "adjacent": 0, "exploratory": 0}

            batches.append({
                "categoryId": b["category_id"],
                "refreshRunId": b["refresh_run_id"],
                "generatedAt": b["generated_at"],
                "targetTotal": b["target_total"],
                "selectedTotal": b["selected_total"],
                "targetByBand": target_by_band,
                "selectedByBand": selected_by_band,
                "shortfallReason": b["shortfall_reason"]
            })

        # Calcular cursor
        next_cursor = None
        if len(rows) == limit:
            next_cursor = str(offset + limit)

        return recommendations, batches, next_cursor
