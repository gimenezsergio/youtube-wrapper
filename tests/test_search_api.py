from unittest.mock import MagicMock
import pytest

from app.auth.encryption import encrypt_token
from app.db import get_db_connection
from app.services.search_service import SearchService


@pytest.fixture
def auth_client(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"
        sess["csrf_token"] = "mock-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "mock-csrf-token"
    return client


def test_search_unauth(client):
    # Sin autenticación
    resp_unauth = client.get("/api/v1/search?query=test")
    assert resp_unauth.status_code == 401


def test_search_validation_empty_query(auth_client):
    # Con query vacía
    resp_empty = auth_client.get("/api/v1/search?query=")
    assert resp_empty.status_code == 400
    assert resp_empty.json["error"]["code"] == "VALIDATION_ERROR"


def test_search_prioritizes_subscribed_and_filters_properly(app, auth_client, db):
    # 1. Crear credenciales para pasar _get_valid_access_token
    db.execute("""
        INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at)
        VALUES (1, ?, ?, '2099-01-01T00:00:00Z', 'now')
    """, (encrypt_token("mock-token"), encrypt_token("mock-refresh")))

    # 2. Crear canales:
    # Canal 1: Suscrito ("Canal Tech", UC_SUB)
    db.execute("""
        INSERT INTO channels (id, youtube_channel_id, title, is_subscribed, is_blocked, created_at, updated_at)
        VALUES (1, 'UC_SUB', 'Canal Tech Suscrito', 1, 0, 'now', 'now')
    """)
    # Canal 2: Bloqueado ("Canal Spam", UC_BLOCKED)
    db.execute("""
        INSERT INTO channels (id, youtube_channel_id, title, is_subscribed, is_blocked, created_at, updated_at)
        VALUES (2, 'UC_BLOCKED', 'Canal Spam', 0, 1, 'now', 'now')
    """)

    # 3. Crear video preexistente ya visto en el sistema
    db.execute("""
        INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, duration_seconds, content_type, created_at, updated_at)
        VALUES (10, 'vid_watched', 1, 'Video Ya Visto', 'now', 600, 'video', 'now', 'now')
    """)
    db.execute("""
        INSERT INTO video_user_state (video_id, opened_at, open_count, watched, updated_at)
        VALUES (10, 'now', 1, 1, 'now')
    """)
    db.commit()

    # 4. Mockear YouTubeGateway
    mock_gateway = MagicMock()
    # search_videos devolverá:
    # - vid_from_sub: de UC_SUB (suscrito, duración 500s)
    # - vid_external: de UC_EXT (externo, duración 700s)
    # - vid_short: de UC_EXT (short, duración 120s) -> debe ser excluido
    # - vid_blocked: de UC_BLOCKED (bloqueado) -> debe ser excluido
    # - vid_watched: de UC_SUB (ya visto) -> debe ser excluido
    mock_gateway.search_videos.return_value = [
        {
            "youtube_video_id": "vid_from_sub",
            "youtube_channel_id": "UC_SUB",
            "channel_title": "Canal Tech Suscrito",
            "title": "Tutorial Python Pro",
            "description": "Aprende Python",
            "published_at": "2026-05-01T10:00:00Z",
            "thumbnail_url": "thumb1.jpg"
        },
        {
            "youtube_video_id": "vid_external",
            "youtube_channel_id": "UC_EXT",
            "channel_title": "Canal Externo Nuevo",
            "title": "Curso Avanzado Python",
            "description": "Python avanzado",
            "published_at": "2026-05-02T10:00:00Z",
            "thumbnail_url": "thumb2.jpg"
        },
        {
            "youtube_video_id": "vid_short",
            "youtube_channel_id": "UC_EXT",
            "channel_title": "Canal Externo Nuevo",
            "title": "Short Tip Python",
            "description": "tip corto",
            "published_at": "2026-05-03T10:00:00Z",
            "thumbnail_url": "thumb3.jpg"
        },
        {
            "youtube_video_id": "vid_blocked",
            "youtube_channel_id": "UC_BLOCKED",
            "channel_title": "Canal Spam",
            "title": "Spam Python",
            "description": "spam",
            "published_at": "2026-05-04T10:00:00Z",
            "thumbnail_url": "thumb4.jpg"
        },
        {
            "youtube_video_id": "vid_watched",
            "youtube_channel_id": "UC_SUB",
            "channel_title": "Canal Tech Suscrito",
            "title": "Video Ya Visto",
            "description": "visto",
            "published_at": "2026-05-05T10:00:00Z",
            "thumbnail_url": "thumb5.jpg"
        }
    ]

    mock_gateway.fetch_videos_details.return_value = [
        {"youtube_video_id": "vid_from_sub", "duration_seconds": 500, "content_type": "video"},
        {"youtube_video_id": "vid_external", "duration_seconds": 700, "content_type": "video"},
        {"youtube_video_id": "vid_short", "duration_seconds": 120, "content_type": "video"},
        {"youtube_video_id": "vid_blocked", "duration_seconds": 400, "content_type": "video"},
        {"youtube_video_id": "vid_watched", "duration_seconds": 600, "content_type": "video"},
    ]

    # Probar SearchService directamente con el mock_gateway
    service = SearchService(gateway=mock_gateway)
    res = service.search(db, "Python")

    assert res["query"] == "Python"
    assert res["totalFound"] == 2

    # 1. En canales suscritos solo debe estar vid_from_sub
    sub_items = res["fromSubscribedChannels"]
    assert len(sub_items) == 1
    assert sub_items[0]["youtubeVideoId"] == "vid_from_sub"
    assert sub_items[0]["channel"]["subscribed"] is True

    # 2. En canales externos solo debe estar vid_external
    ext_items = res["fromExternalChannels"]
    assert len(ext_items) == 1
    assert ext_items[0]["youtubeVideoId"] == "vid_external"
    assert ext_items[0]["channel"]["subscribed"] is False

    # 3. Comprobar que en la base de datos se persistieron ambos videos con sus IDs
    saved_vids = db.execute("SELECT youtube_video_id FROM videos WHERE youtube_video_id IN ('vid_from_sub', 'vid_external')").fetchall()
    assert len(saved_vids) == 2
