from unittest.mock import MagicMock
import pytest

from app.auth.encryption import encrypt_token
from app.services.video_service import VideoService


@pytest.fixture
def auth_client(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"
        sess["csrf_token"] = "mock-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "mock-csrf-token"
    return client


def test_sync_liked_videos_and_exclusion(app, auth_client, db):
    # 1. Crear canal y videos iniciales en la DB
    db.execute("""
        INSERT INTO channels (id, youtube_channel_id, title, is_subscribed, created_at, updated_at)
        VALUES (1, 'UC_test', 'Test Channel', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
    """)
    db.execute("""
        INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, duration_seconds, content_type, created_at, updated_at)
        VALUES (10, 'yt_like_1', 1, 'Liked Video Title', '2026-01-01T00:00:00Z', 300, 'video', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
    """)
    db.execute("""
        INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, duration_seconds, content_type, created_at, updated_at)
        VALUES (11, 'yt_normal_1', 1, 'Normal Video Title', '2026-01-01T00:00:00Z', 300, 'video', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
    """)
    db.commit()

    # Comprobar que inicialmente ambos videos aparecen en /api/v1/videos
    res = auth_client.get("/api/v1/videos")
    assert res.status_code == 200
    items = res.json["items"]
    assert len(items) == 2

    # Mock gateway para simular retorno de fetch_liked_videos
    mock_gateway = MagicMock()
    mock_gateway.fetch_liked_videos.return_value = {
        "items": [{
            "youtube_video_id": "yt_like_1",
            "youtube_channel_id": "UC_test",
            "channel_title": "Test Channel",
            "title": "Liked Video Title",
            "description": "desc",
            "published_at": "2026-01-01T00:00:00Z",
            "thumbnail_url": "",
            "duration_seconds": 300
        }],
        "nextPageToken": None
    }

    with app.app_context():
        # Guardar credenciales falsas en DB para que la obtención del token no falle
        db.execute("""
            INSERT INTO credentials (access_token, refresh_token, expires_at, updated_at)
            VALUES (?, ?, '2099-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """, (encrypt_token("mock_access_token"), encrypt_token("mock_refresh_token")))
        db.commit()

        service = VideoService(gateway=mock_gateway)
        stats = service.sync_liked_videos(db)
        assert stats["processed_liked_videos"] == 1

        # Verificar que video_user_state tenga liked = 1 para video_id 10
        row = db.execute("SELECT liked FROM video_user_state WHERE video_id = 10").fetchone()
        assert row is not None
        assert row["liked"] == 1

    # Consultar nuevamente /api/v1/videos y verificar que el video con liked = 1 NO aparece
    res2 = auth_client.get("/api/v1/videos")
    assert res2.status_code == 200
    items2 = res2.json["items"]
    assert len(items2) == 1
    assert items2[0]["id"] == 11
    assert items2[0]["title"] == "Normal Video Title"
