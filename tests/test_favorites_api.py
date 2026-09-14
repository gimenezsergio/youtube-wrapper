import json

import pytest

from app.auth.encryption import encrypt_token
from app.db import get_db_connection
from app.services.video_service import VideoService
from tests.fakes.youtube_gateway import FakeYouTubeGateway


@pytest.fixture
def auth_client(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"
        sess["csrf_token"] = "mock-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "mock-csrf-token"
    return client


@pytest.fixture
def seed_data(app):
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        enc_access = encrypt_token("mock-access-token")
        enc_refresh = encrypt_token("mock-refresh-token")
        conn.execute("""
            INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at)
            VALUES (1, ?, ?, '2026-08-30T00:00:00Z', 'now')
        """, (enc_access, enc_refresh))
        conn.execute("""
            INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
            VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')
        """)
        conn.execute("""
            INSERT INTO channels (
                id, youtube_channel_id, title, description, thumbnail_url,
                uploads_playlist_id, is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
            ) VALUES (10, 'UC_A', 'Canal A', 'Desc A', 'thumbA', 'UU_A', 1, 0, 0, 'now', 'now')
        """)
        conn.execute("""
            INSERT INTO channel_categories (channel_id, category_id, source, created_at)
            VALUES (10, 1, 'manual', 'now')
        """)
        conn.commit()
        conn.close()


def test_favorite_video_lifecycle(auth_client, seed_data, app):
    """Prueba completa del ciclo de marcado, consulta y desmarcado de favoritos."""
    fake_gateway = FakeYouTubeGateway()
    service = VideoService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        service.sync_videos(conn)
        conn.close()

    # 1. Al inicio, la lista de favoritos debe estar vacía
    resp_empty = auth_client.get("/api/v1/videos/favorites")
    assert resp_empty.status_code == 200
    data_empty = json.loads(resp_empty.data)
    assert len(data_empty["items"]) == 0

    # 2. Marcar video (ID 1) como favorito
    resp_fav = auth_client.put("/api/v1/videos/1/favorite", json={"favorited": True})
    assert resp_fav.status_code == 200
    data_fav = json.loads(resp_fav.data)
    assert data_fav["videoId"] == 1
    assert data_fav["favorited"] is True
    assert data_fav["favoritedAt"] is not None

    # 3. Consultar feed: debe incluir favorited=True
    resp_feed = auth_client.get("/api/v1/videos?view=feed")
    assert resp_feed.status_code == 200
    data_feed = json.loads(resp_feed.data)
    fav_item = next(v for v in data_feed["items"] if v["id"] == 1)
    assert fav_item["favorited"] is True
    assert fav_item["favoritedAt"] is not None

    # 4. Consultar endpoint de favoritos
    resp_list = auth_client.get("/api/v1/videos/favorites")
    assert resp_list.status_code == 200
    data_list = json.loads(resp_list.data)
    assert len(data_list["items"]) == 1
    assert data_list["items"][0]["id"] == 1
    assert data_list["items"][0]["favorited"] is True

    # 5. Desmarcar como favorito
    resp_unfav = auth_client.put("/api/v1/videos/1/favorite", json={"favorited": False})
    assert resp_unfav.status_code == 200
    data_unfav = json.loads(resp_unfav.data)
    assert data_unfav["favorited"] is False
    assert data_unfav["favoritedAt"] is None

    # 6. Lista de favoritos vuelve a quedar vacía
    resp_empty_2 = auth_client.get("/api/v1/videos/favorites")
    data_empty_2 = json.loads(resp_empty_2.data)
    assert len(data_empty_2["items"]) == 0


def test_favorite_validation(auth_client, seed_data, app):
    """Validación de payloads inválidos en endpoint de favoritos."""
    # Video inexistente (404)
    resp_404 = auth_client.put("/api/v1/videos/9999/favorite", json={"favorited": True})
    assert resp_404.status_code == 404

    # Body inválido (no boolean)
    resp_422 = auth_client.put("/api/v1/videos/1/favorite", json={"favorited": "yes"})
    assert resp_422.status_code == 422
