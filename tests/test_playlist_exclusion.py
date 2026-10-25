import pytest
from app.db import get_db_connection
from app.services.playlist_exclusion_service import PlaylistExclusionService
from tests.fakes.youtube_gateway import FakeYouTubeGateway


@pytest.fixture
def auth_client(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"
        sess["csrf_token"] = "mock-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "mock-csrf-token"
    return client


def test_extract_playlist_id():
    url = "https://www.youtube.com/playlist?list=PLo8Z6taNbZ7MKN7xkJYlHmXBLGDY7sOUu"
    assert PlaylistExclusionService.extract_playlist_id(url) == "PLo8Z6taNbZ7MKN7xkJYlHmXBLGDY7sOUu"

    direct_id = "PLo8Z6taNbZ7MKN7xkJYlHmXBLGDY7sOUu"
    assert PlaylistExclusionService.extract_playlist_id(direct_id) == "PLo8Z6taNbZ7MKN7xkJYlHmXBLGDY7sOUu"


def test_playlist_exclusion_service_crud_and_video_filtering(app):
    fake_gw = FakeYouTubeGateway()
    fake_gw.playlist_items["PL_TEST"] = {
        "items": [
            {"youtube_video_id": "vid_ex_1", "title": "Video Excluido 1", "published_at": "2026-01-01T00:00:00Z"},
            {"youtube_video_id": "vid_ex_2", "title": "Video Excluido 2", "published_at": "2026-01-02T00:00:00Z"},
        ],
        "nextPageToken": None
    }

    service = PlaylistExclusionService(gateway=fake_gw)

    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])

        # Insertar canal y videos de prueba
        db.execute("""
            INSERT INTO channels (id, youtube_channel_id, title, is_subscribed, is_blocked, created_at, updated_at)
            VALUES (101, 'UC_FAV_TEST', 'Canal Favorito Test', 1, 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """)
        db.execute("""
            INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, duration_seconds, content_type, created_at, updated_at)
            VALUES 
                (501, 'vid_ex_1', 101, 'Video Excluido 1', '2026-01-01T00:00:00Z', 600, 'video', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
                (502, 'vid_ok_1', 101, 'Video Permitido 1', '2026-01-03T00:00:00Z', 600, 'video', '2026-01-03T00:00:00Z', '2026-01-03T00:00:00Z')
        """)
        db.commit()

        # Excluir la playlist
        res = service.exclude_playlist(db, "https://www.youtube.com/playlist?list=PL_TEST", title="Playlist de Prueba")
        assert res["youtubePlaylistId"] == "PL_TEST"
        assert res["videosExcludedCount"] == 2

        # Comprobar listado
        excluded = service.list_excluded_playlists(db)
        assert len(excluded) >= 1
        p_item = next(p for p in excluded if p["youtubePlaylistId"] == "PL_TEST")
        assert p_item["title"] == "Playlist de Prueba"
        assert p_item["videoCount"] == 2

        # Comprobar exclusión en videos API
        cursor = db.execute("""
            SELECT v.youtube_video_id
            FROM videos v
            JOIN channels c ON v.channel_id = c.id
            WHERE c.is_blocked = 0
              AND v.youtube_video_id NOT IN (SELECT youtube_video_id FROM excluded_playlist_videos)
        """)
        visible_video_ids = [r["youtube_video_id"] for r in cursor.fetchall()]
        assert "vid_ok_1" in visible_video_ids
        assert "vid_ex_1" not in visible_video_ids

        # Remover exclusión
        removed = service.remove_excluded_playlist(db, "PL_TEST")
        assert removed is True

        cursor = db.execute("SELECT COUNT(*) FROM excluded_playlist_videos WHERE playlist_id = 'PL_TEST'")
        assert cursor.fetchone()[0] == 0

        db.close()


def test_api_settings_excluded_playlists(auth_client, app):
    # GET settings exclusions
    resp = auth_client.get("/api/v1/settings/discovery-exclusions")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "excludedPlaylists" in data
    # Comprobar que la playlist de 'Los minutos del Odio' existe de la migración
    odio = next((p for p in data["excludedPlaylists"] if p["youtubePlaylistId"] == "PLo8Z6taNbZ7MKN7xkJYlHmXBLGDY7sOUu"), None)
    assert odio is not None
    assert odio["title"] == "Los minutos del Odio"

    # POST agregar playlist
    resp_post = auth_client.post("/api/v1/settings/excluded-playlists", json={
        "playlist": "PL_API_TEST",
        "title": "Prueba API"
    })
    assert resp_post.status_code == 201

    # DELETE remover playlist
    resp_del = auth_client.delete("/api/v1/settings/excluded-playlists/PL_API_TEST")
    assert resp_del.status_code == 204
