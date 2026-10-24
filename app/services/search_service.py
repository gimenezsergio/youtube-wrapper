import logging
from typing import Any, Dict, List

from app.api.videos import _serialize_video
from app.integrations.youtube.gateway import YouTubeGateway
from app.repositories.discovery_repository import DiscoveryRepository
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, gateway=None):
        self.gateway = gateway or YouTubeGateway()

    def search(self, db, query: str, limit: int = 25) -> Dict[str, Any]:
        """
        Búsqueda inteligente en tiempo real en la API de YouTube priorizando canales suscritos.
        - Prioridad 1: Videos de creadores suscritos afines al término.
        - Prioridad 2: Videos externos limpios de YouTube.
        - Filtros: Descarte automático de Shorts (<= 180s), canales bloqueados y videos ya vistos o con like.
        """
        query = (query or "").strip()
        if not query:
            return {
                "query": "",
                "fromSubscribedChannels": [],
                "fromExternalChannels": [],
                "totalFound": 0
            }

        # 1. Obtener access token válido
        sub_service = SubscriptionService(gateway=self.gateway)
        try:
            access_token = sub_service._get_valid_access_token(db)
        except Exception as e:
            logger.error(f"Error obteniendo token de acceso para búsqueda: {e}")
            raise Exception(f"No se pudo autorizar la búsqueda en YouTube: {e}") from e

        # 2. Identificar si hay canales suscritos específicos con temática afín
        cursor = db.execute("""
            SELECT id, youtube_channel_id, title, description
            FROM channels
            WHERE is_subscribed = 1 AND is_blocked = 0
              AND (title LIKE ? OR description LIKE ?)
            LIMIT 2
        """, (f"%{query}%", f"%{query}%"))
        matching_subscribed_channels = cursor.fetchall()

        raw_videos = []
        seen_video_ids = set()

        # 2.1 Búsqueda focalizada en canal(es) suscrito(s) afín(es)
        for ch in matching_subscribed_channels:
            try:
                ch_videos = self.gateway.search_videos(
                    access_token, q=query, limit=10, channel_id=ch["youtube_channel_id"]
                )
                for v in ch_videos:
                    vid_id = v.get("youtube_video_id")
                    if vid_id and vid_id not in seen_video_ids:
                        seen_video_ids.add(vid_id)
                        raw_videos.append(v)
            except Exception as e:
                logger.warning(f"Fallo al buscar en canal {ch['youtube_channel_id']}: {e}")

        # 2.2 Búsqueda general en YouTube API
        try:
            general_videos = self.gateway.search_videos(
                access_token, q=query, limit=min(limit * 2, 50)
            )
            for v in general_videos:
                vid_id = v.get("youtube_video_id")
                if vid_id and vid_id not in seen_video_ids:
                    seen_video_ids.add(vid_id)
                    raw_videos.append(v)
        except Exception as e:
            logger.error(f"Error en búsqueda general de YouTube: {e}")
            # Si al menos tenemos videos de canales afines, continuamos
            if not raw_videos:
                raise

        if not raw_videos:
            return {
                "query": query,
                "fromSubscribedChannels": [],
                "fromExternalChannels": [],
                "totalFound": 0
            }

        # 3. Hidratar detalles de los videos (duración y content_type)
        candidate_ids = [v["youtube_video_id"] for v in raw_videos]
        try:
            details_list = self.gateway.fetch_videos_details(access_token, candidate_ids)
            details_map = {d["youtube_video_id"]: d for d in details_list}
        except Exception as e:
            logger.warning(f"No se pudieron hidratar detalles de videos: {e}")
            details_map = {}

        # 4. Obtener listas de exclusión locales
        blocked_cursor = db.execute("SELECT youtube_channel_id FROM channels WHERE is_blocked = 1")
        blocked_yt_ids = {r["youtube_channel_id"] for r in blocked_cursor.fetchall() if r["youtube_channel_id"]}

        watched_cursor = db.execute("""
            SELECT v.youtube_video_id 
            FROM video_user_state vus
            JOIN videos v ON vus.video_id = v.id
            WHERE vus.watched = 1 OR vus.liked = 1
        """)
        watched_yt_ids = {r["youtube_video_id"] for r in watched_cursor.fetchall()}

        hidden_cursor = db.execute("""
            SELECT v.youtube_video_id
            FROM discovery_feedback df
            JOIN videos v ON df.video_id = v.id
            WHERE df.action = 'hide_video'
        """)
        hidden_yt_ids = {r["youtube_video_id"] for r in hidden_cursor.fetchall()}

        sub_cursor = db.execute(
            "SELECT youtube_channel_id FROM channels WHERE is_subscribed = 1 OR is_locally_followed = 1"
        )
        subscribed_yt_ids = {r["youtube_channel_id"] for r in sub_cursor.fetchall() if r["youtube_channel_id"]}

        # 5. Filtrar y persistir en la base de datos
        filtered_videos_meta = []
        for v in raw_videos:
            yt_vid_id = v["youtube_video_id"]
            yt_ch_id = v.get("youtube_channel_id")

            # Excluir si el canal está bloqueado
            if yt_ch_id and yt_ch_id in blocked_yt_ids:
                continue

            # Excluir si ya fue visto o tiene like
            if yt_vid_id in watched_yt_ids:
                continue

            # Excluir si está ocultado por feedback
            if yt_vid_id in hidden_yt_ids:
                continue

            det = details_map.get(yt_vid_id, {})
            duration = det.get("duration_seconds") if "duration_seconds" in det else v.get("duration_seconds")
            content_type = det.get("content_type", v.get("content_type", "video"))

            # Excluir Shorts (videos con duración <= 180 segundos)
            if duration is not None and duration <= 180:
                continue

            channel_data = {
                "youtube_channel_id": yt_ch_id,
                "title": v.get("channel_title") or "Canal Desconocido",
                "description": "",
                "thumbnail_url": ""
            }
            video_data = {
                "youtube_video_id": yt_vid_id,
                "title": v.get("title") or "Sin título",
                "description": v.get("description") or "",
                "published_at": v.get("published_at") or "",
                "duration_seconds": duration,
                "thumbnail_url": v.get("thumbnail_url") or "",
                "content_type": content_type
            }

            try:
                ch_id, vid_id = DiscoveryRepository.upsert_channel_and_video(db, channel_data, video_data)
                filtered_videos_meta.append({
                    "video_id": vid_id,
                    "channel_id": ch_id,
                    "youtube_channel_id": yt_ch_id
                })
            except Exception as ex:
                logger.warning(f"Error al guardar video {yt_vid_id}: {ex}")

        db.commit()

        if not filtered_videos_meta:
            return {
                "query": query,
                "fromSubscribedChannels": [],
                "fromExternalChannels": [],
                "totalFound": 0
            }

        # 6. Serializar los videos guardados con sus metadatos completos
        video_db_ids = [fv["video_id"] for fv in filtered_videos_meta]
        placeholders = ",".join("?" for _ in video_db_ids)

        query_sql = f"""
            SELECT v.*,
                   c.youtube_channel_id as channel_youtube_channel_id,
                   c.title as channel_title,
                   c.description as channel_description,
                   c.thumbnail_url as channel_thumbnail_url,
                   c.is_subscribed as channel_is_subscribed,
                   c.is_locally_followed as channel_is_locally_followed,
                   c.is_blocked as channel_is_blocked,
                   c.is_favorite as channel_is_favorite,
                   vus.watched as video_watched,
                   vus.opened_at as video_opened_at,
                   vus.watched_source as video_watched_source,
                   vus.favorited as video_favorited,
                   vus.favorited_at as video_favorited_at
            FROM videos v
            JOIN channels c ON v.channel_id = c.id
            LEFT JOIN video_user_state vus ON v.id = vus.video_id
            WHERE v.id IN ({placeholders})
            ORDER BY v.published_at DESC
        """
        rows = db.execute(query_sql, video_db_ids).fetchall()
        row_map = {r["id"]: r for r in rows}

        from_subscribed = []
        from_external = []

        for fv in filtered_videos_meta:
            vid_id = fv["video_id"]
            r = row_map.get(vid_id)
            if not r:
                continue
            serialized = _serialize_video(r)
            if (
                fv["youtube_channel_id"] in subscribed_yt_ids
                or r["channel_is_subscribed"]
                or r["channel_is_locally_followed"]
            ):
                from_subscribed.append(serialized)
            else:
                from_external.append(serialized)

        return {
            "query": query,
            "fromSubscribedChannels": from_subscribed,
            "fromExternalChannels": from_external,
            "totalFound": len(from_subscribed) + len(from_external)
        }
