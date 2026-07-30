from datetime import datetime, timezone

from app.integrations.youtube.gateway import YouTubeGateway
from app.services.subscription_service import SubscriptionService


def get_utc_now_iso():
    """Retorna la fecha y hora UTC actual en formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


class VideoService:
    def __init__(self, gateway=None):
        self.gateway = gateway or YouTubeGateway()

    def _fetch_incremental_channel_videos(self, db, access_token, sub_service, channel) -> list[dict]:
        """Obtiene videos de forma incremental para un único canal."""
        playlist_id = channel["uploads_playlist_id"]
        if not playlist_id:
            return []

        channel_id = channel["id"]

        # Obtener videos existentes con duración ya guardada para este canal
        cursor = db.execute("""
            SELECT youtube_video_id
            FROM videos
            WHERE channel_id = ? AND duration_seconds IS NOT NULL
        """, (channel_id,))
        existing_ids = {row["youtube_video_id"] for row in cursor.fetchall()}

        # Consultar items de la playlist
        try:
            result = self.gateway.fetch_playlist_items(access_token, playlist_id)
        except PermissionError:
            # Reintento único forzando refresco
            access_token = sub_service._force_refresh_token(db)
            result = self.gateway.fetch_playlist_items(access_token, playlist_id)

        playlist_items = result.get("items", [])
        channel_candidates = []

        # Agregar a candidatos de forma incremental
        for item in playlist_items:
            yt_video_id = item["youtube_video_id"]

            # Si el video ya existe y está totalmente hidratado, paramos el canal
            if yt_video_id in existing_ids:
                break

            channel_candidates.append({
                "youtube_video_id": yt_video_id,
                "channel_id": channel_id,
                "title": item["title"],
                "description": item["description"],
                "published_at": item["published_at"],
                "thumbnail_url": item["thumbnail_url"]
            })

        return channel_candidates

    def sync_videos(self, db) -> dict:
        """
        Sincroniza de forma incremental los videos de los canales activos y no bloqueados.
        Retorna estadísticas de la operación.
        """
        # 1. Obtener access_token activo
        sub_service = SubscriptionService(gateway=self.gateway)
        try:
            access_token = sub_service._get_valid_access_token(db)
        except Exception as e:
            raise Exception(f"No se pudo obtener access token para sincronizar videos: {e}") from e

        # 2. Obtener canales activos no bloqueados
        cursor = db.execute("""
            SELECT id, youtube_channel_id, title, uploads_playlist_id
            FROM channels
            WHERE (is_subscribed = 1 OR is_locally_followed = 1)
              AND is_blocked = 0
        """)
        channels = cursor.fetchall()
        if not channels:
            return {"created": 0, "updated": 0, "processed_channels": 0}

        candidates = []
        processed_channels_count = 0

        # 3. Consultar incrementalmente cada playlist de subidas
        for channel in channels:
            playlist_id = channel["uploads_playlist_id"]
            if playlist_id:
                processed_channels_count += 1
                chan_videos = self._fetch_incremental_channel_videos(db, access_token, sub_service, channel)
                candidates.extend(chan_videos)

        if not candidates:
            return {"created": 0, "updated": 0, "processed_channels": processed_channels_count}

        # 4. Hidratar en lote de 50 (snippet, contentDetails)
        candidate_ids = [c["youtube_video_id"] for c in candidates]
        try:
            details_list = self.gateway.fetch_videos_details(access_token, candidate_ids)
        except PermissionError:
            access_token = sub_service._force_refresh_token(db)
            details_list = self.gateway.fetch_videos_details(access_token, candidate_ids)

        details_map = {
            d["youtube_video_id"]: {
                "duration_seconds": d["duration_seconds"],
                "content_type": d["content_type"]
            }
            for d in details_list
        }

        # 5. Guardar en base de datos con upsert transaccional
        created_count = 0
        updated_count = 0
        now_iso = get_utc_now_iso()

        # Determinar cuáles existen previamente en la base de datos para contar creados vs actualizados
        placeholders = ",".join("?" for _ in candidate_ids)
        cursor = db.execute(
            f"SELECT youtube_video_id FROM videos WHERE youtube_video_id IN ({placeholders})",
            candidate_ids
        )
        already_existing_ids = {row["youtube_video_id"] for row in cursor.fetchall()}

        try:
            for cand in candidates:
                yt_video_id = cand["youtube_video_id"]
                details = details_map.get(yt_video_id, {"duration_seconds": None, "content_type": "unknown"})

                db.execute("""
                    INSERT INTO videos (
                        youtube_video_id, channel_id, title, description, published_at,
                        duration_seconds, thumbnail_url, content_type, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(youtube_video_id) DO UPDATE SET
                        title = excluded.title,
                        description = excluded.description,
                        published_at = excluded.published_at,
                        duration_seconds = COALESCE(excluded.duration_seconds, duration_seconds),
                        thumbnail_url = excluded.thumbnail_url,
                        content_type = excluded.content_type,
                        updated_at = excluded.updated_at
                """, (
                    yt_video_id,
                    cand["channel_id"],
                    cand["title"],
                    cand["description"],
                    cand["published_at"],
                    details["duration_seconds"],
                    cand["thumbnail_url"],
                    details["content_type"],
                    now_iso,
                    now_iso
                ))

                if yt_video_id in already_existing_ids:
                    updated_count += 1
                else:
                    created_count += 1

            db.commit()
            return {
                "created": created_count,
                "updated": updated_count,
                "processed_channels": processed_channels_count
            }
        except Exception:
            db.rollback()
            raise
