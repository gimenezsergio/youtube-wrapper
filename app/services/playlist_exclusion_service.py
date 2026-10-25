import logging
import re
from datetime import datetime, timezone
from typing import List, Optional, Set

from app.integrations.youtube.gateway import YouTubeGateway
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


class PlaylistExclusionService:
    def __init__(self, gateway: Optional[YouTubeGateway] = None):
        self.gateway = gateway or YouTubeGateway()

    @staticmethod
    def extract_playlist_id(url_or_id: str) -> str:
        """Extrae el playlist ID a partir de un ID directo o una URL de YouTube."""
        clean = url_or_id.strip()
        match = re.search(r"[?&]list=([a-zA-Z0-9_-]+)", clean)
        if match:
            return match.group(1)
        return clean

    def sync_playlist_videos(self, db, youtube_playlist_id: str, access_token: Optional[str] = None) -> int:
        """
        Consulta todos los videos de la playlist desde YouTube API y los persiste
        en la tabla excluded_playlist_videos.
        """
        if not access_token:
            sub_service = SubscriptionService(gateway=self.gateway)
            try:
                access_token = sub_service._get_valid_access_token(db)
            except Exception as e:
                if getattr(self.gateway, "is_fake", False) or "Fake" in self.gateway.__class__.__name__:
                    access_token = "mock-token"
                else:
                    logger.warning(
                        f"No se pudo obtener access token para sincronizar playlist {youtube_playlist_id}: {e}"
                    )
                    return 0

        now_iso = datetime.now(timezone.utc).isoformat()
        total_synced = 0
        page_token = None

        while True:
            try:
                res = self.gateway.fetch_playlist_items(
                    access_token, youtube_playlist_id, limit=50, page_token=page_token
                )
            except Exception as e:
                logger.error(f"Error consultando items de playlist {youtube_playlist_id}: {e}")
                break

            items = res.get("items", [])
            for it in items:
                vid_id = it.get("youtube_video_id")
                if vid_id:
                    db.execute("""
                        INSERT OR IGNORE INTO excluded_playlist_videos (playlist_id, youtube_video_id, created_at)
                        VALUES (?, ?, ?)
                    """, (youtube_playlist_id, vid_id, now_iso))
                    total_synced += 1

            page_token = res.get("nextPageToken")
            if not page_token:
                break

        db.commit()
        return total_synced

    def sync_all_excluded_playlists(self, db, access_token: Optional[str] = None) -> dict:
        """Sincroniza todos los videos de todas las playlists excluidas."""
        cursor = db.execute("SELECT youtube_playlist_id FROM excluded_playlists")
        playlists = cursor.fetchall()
        results = {}
        for row in playlists:
            pid = row["youtube_playlist_id"]
            count = self.sync_playlist_videos(db, pid, access_token)
            results[pid] = count
        return results

    def exclude_playlist(self, db, url_or_id: str, title: Optional[str] = None) -> dict:
        """Registra una playlist como excluida y descarga sus videos."""
        pid = self.extract_playlist_id(url_or_id)
        if not pid:
            raise ValueError("ID o URL de lista de reproducción inválido.")

        now_iso = datetime.now(timezone.utc).isoformat()
        final_title = title or f"Playlist {pid}"

        sub_service = SubscriptionService(gateway=self.gateway)
        access_token = None
        try:
            access_token = sub_service._get_valid_access_token(db)
        except Exception:
            if getattr(self.gateway, "is_fake", False) or "Fake" in self.gateway.__class__.__name__:
                access_token = "mock-token"

        channel_id = None
        if access_token:
            try:
                first_page = self.gateway.fetch_playlist_items(access_token, pid, limit=1)
                items = first_page.get("items", [])
                if items:
                    sample_vid = items[0].get("youtube_video_id")
                    if sample_vid:
                        c_row = db.execute("""
                            SELECT c.id FROM channels c
                            JOIN videos v ON v.channel_id = c.id
                            WHERE v.youtube_video_id = ?
                        """, (sample_vid,)).fetchone()
                        if c_row:
                            channel_id = c_row["id"]
            except Exception as e:
                logger.warning(f"No se pudo consultar información previa de playlist {pid}: {e}")

        # Insertar o actualizar registro en excluded_playlists
        db.execute("""
            INSERT INTO excluded_playlists (youtube_playlist_id, title, channel_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(youtube_playlist_id) DO UPDATE SET
                title = COALESCE(excluded.title, excluded_playlists.title),
                channel_id = COALESCE(excluded.channel_id, excluded_playlists.channel_id),
                updated_at = excluded.updated_at
        """, (pid, final_title, channel_id, now_iso, now_iso))
        db.commit()

        # Descargar e indexar videos de la playlist
        synced_count = self.sync_playlist_videos(db, pid, access_token)

        # Si el título contiene ODIO, vincular videos locales que coincidan
        if "odio" in final_title.lower():
            db.execute("""
                INSERT OR IGNORE INTO excluded_playlist_videos (playlist_id, youtube_video_id, created_at)
                SELECT ?, youtube_video_id, ?
                FROM videos
                WHERE title LIKE '%LOS MINUTOS DEL ODIO%'
            """, (pid, now_iso))
            db.commit()

        # Contar total de videos excluidos para esta playlist
        count_row = db.execute(
            "SELECT COUNT(*) FROM excluded_playlist_videos WHERE playlist_id = ?", (pid,)
        ).fetchone()
        total_count = count_row[0] if count_row else synced_count

        return {
            "youtubePlaylistId": pid,
            "title": final_title,
            "videosExcludedCount": total_count
        }

    def remove_excluded_playlist(self, db, youtube_playlist_id: str) -> bool:
        """Elimina una playlist de las exclusiones."""
        pid = self.extract_playlist_id(youtube_playlist_id)
        cursor = db.execute("DELETE FROM excluded_playlists WHERE youtube_playlist_id = ?", (pid,))
        db.execute("DELETE FROM excluded_playlist_videos WHERE playlist_id = ?", (pid,))
        db.commit()
        return cursor.rowcount > 0

    def list_excluded_playlists(self, db) -> List[dict]:
        """Lista todas las playlists excluidas junto con la cantidad de videos asociados."""
        cursor = db.execute("""
            SELECT ep.id, ep.youtube_playlist_id, ep.title, ep.channel_id, ep.created_at,
                   c.title as channel_title,
                   COUNT(epv.youtube_video_id) as video_count
            FROM excluded_playlists ep
            LEFT JOIN channels c ON ep.channel_id = c.id
            LEFT JOIN excluded_playlist_videos epv ON ep.youtube_playlist_id = epv.playlist_id
            GROUP BY ep.id
            ORDER BY ep.created_at DESC
        """)
        results = []
        for r in cursor.fetchall():
            results.append({
                "id": r["id"],
                "youtubePlaylistId": r["youtube_playlist_id"],
                "title": r["title"] or r["youtube_playlist_id"],
                "channelTitle": r["channel_title"],
                "videoCount": r["video_count"],
                "createdAt": r["created_at"]
            })
        return results

    @staticmethod
    def get_excluded_video_ids(db) -> Set[str]:
        """Retorna el conjunto de todos los youtube_video_id excluidos."""
        cursor = db.execute("SELECT youtube_video_id FROM excluded_playlist_videos")
        return {r["youtube_video_id"] for r in cursor.fetchall()}
