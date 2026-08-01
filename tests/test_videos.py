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
        # Crear credenciales
        enc_access = encrypt_token("mock-access-token")
        enc_refresh = encrypt_token("mock-refresh-token")
        conn.execute("""
            INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at)
            VALUES (1, ?, ?, '2026-08-30T00:00:00Z', 'now')
        """, (enc_access, enc_refresh))
        # Crear categorías
        conn.execute("""
            INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
            VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')
        """)
        conn.execute("""
            INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
            VALUES (2, 'Cat B', 'cat-b', 2, 'now', 'now')
        """)
        # Crear canales
        conn.execute("""
            INSERT INTO channels (
                id, youtube_channel_id, title, description, thumbnail_url,
                uploads_playlist_id, is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
            ) VALUES (10, 'UC_A', 'Canal A', 'Desc A', 'thumbA', 'UU_A', 1, 0, 0, 'now', 'now')
        """)
        conn.execute("""
            INSERT INTO channels (
                id, youtube_channel_id, title, description, thumbnail_url,
                uploads_playlist_id, is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
            ) VALUES (20, 'UC_B', 'Canal B', 'Desc B', 'thumbB', 'UU_B', 0, 1, 0, 'now', 'now')
        """)
        # Vincular canal A a categoría 1
        conn.execute("""
            INSERT INTO channel_categories (channel_id, category_id, source, created_at)
            VALUES (10, 1, 'manual', 'now')
        """)
        conn.commit()
        conn.close()


def test_videos_sync(seed_data, app):
    """Prueba de sincronización incremental e hidratación en lotes."""
    fake_gateway = FakeYouTubeGateway()
    service = VideoService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        res = service.sync_videos(conn)

        # Deben crearse 3 videos entre ambos canales
        assert res["created"] == 3
        assert res["processed_channels"] == 2

        # Comprobar videos en BD
        rows = conn.execute("""
            SELECT youtube_video_id, title, duration_seconds, content_type
            FROM videos
            ORDER BY published_at DESC
        """).fetchall()
        assert len(rows) == 3
        assert rows[0]["youtube_video_id"] == "vid_1"
        assert rows[0]["duration_seconds"] == 600
        assert rows[0]["content_type"] == "video"

        assert rows[2]["youtube_video_id"] == "vid_3"
        assert rows[2]["duration_seconds"] == 1800
        assert rows[2]["content_type"] == "live"

        # Segunda sincronización: incremental, no debería agregar nada nuevo
        res_dup = service.sync_videos(conn)
        assert res_dup["created"] == 0
        assert res_dup["updated"] == 0

        conn.close()


def test_videos_api_feed(auth_client, seed_data, app):
    """Listar videos en vista Feed con filtros y paginación."""
    fake_gateway = FakeYouTubeGateway()
    service = VideoService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        service.sync_videos(conn)
        conn.close()

    # 1. Feed completo (los 3 videos)
    resp = auth_client.get("/api/v1/videos?view=feed")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert len(data["items"]) == 3
    assert data["view"] == "feed"

    # 2. Filtrar por categoría 1 (solo videos del Canal A: vid_1 y vid_2)
    resp_cat = auth_client.get("/api/v1/videos?view=feed&categoryId=1")
    assert resp_cat.status_code == 200
    data_cat = json.loads(resp_cat.data)
    assert len(data_cat["items"]) == 2
    assert {v["youtubeVideoId"] for v in data_cat["items"]} == {"vid_1", "vid_2"}

    # 3. Paginación por cursor
    resp_page = auth_client.get("/api/v1/videos?view=feed&limit=2")
    data_page = json.loads(resp_page.data)
    assert len(data_page["items"]) == 2
    next_cursor = data_page["nextCursor"]
    assert next_cursor is not None

    resp_next = auth_client.get(f"/api/v1/videos?view=feed&limit=2&cursor={next_cursor}")
    data_next = json.loads(resp_next.data)
    assert len(data_next["items"]) == 1
    assert data_next["items"][0]["youtubeVideoId"] == "vid_3"


def test_videos_api_channels(auth_client, seed_data, app):
    """Listar videos agrupados por canal (view = channels)."""
    fake_gateway = FakeYouTubeGateway()
    service = VideoService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        service.sync_videos(conn)
        conn.close()

    # Vista por canales
    resp = auth_client.get("/api/v1/videos?view=channels")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["view"] == "channels"

    # Debe retornar 2 grupos (Canal A y Canal B)
    assert len(data["items"]) == 2

    group_a = next(g for g in data["items"] if g["channel"]["id"] == 10)
    assert len(group_a["videos"]) == 2
    assert group_a["videos"][0]["youtubeVideoId"] == "vid_1"

    group_b = next(g for g in data["items"] if g["channel"]["id"] == 20)
    assert len(group_b["videos"]) == 1
    assert group_b["videos"][0]["youtubeVideoId"] == "vid_3"


def test_video_user_actions(auth_client, seed_data, app):
    """Registrar apertura y cambiar manualmente estado visto/no visto."""
    fake_gateway = FakeYouTubeGateway()
    service = VideoService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        service.sync_videos(conn)
        conn.close()

    # 1. Registrar apertura de video (vid_1)
    resp_open = auth_client.post("/api/v1/videos/1/open")
    assert resp_open.status_code == 200
    data_open = json.loads(resp_open.data)
    assert data_open["watched"] is True
    assert data_open["url"] == "https://www.youtube.com/watch?v=vid_1"

    # Verificar que aparece como visto
    resp_list = auth_client.get("/api/v1/videos?view=feed&watched=true")
    data_list = json.loads(resp_list.data)
    assert len(data_list["items"]) == 1
    assert data_list["items"][0]["youtubeVideoId"] == "vid_1"

    # 2. Marcar manualmente como no visto
    resp_watched = auth_client.put("/api/v1/videos/1/watched", json={"watched": False})
    assert resp_watched.status_code == 200
    data_watched = json.loads(resp_watched.data)
    assert data_watched["watched"] is False
    assert data_watched["source"] == "manual"

    # Ya no debe aparecer como visto
    resp_list_2 = auth_client.get("/api/v1/videos?view=feed&watched=true")
    data_list_2 = json.loads(resp_list_2.data)
    assert len(data_list_2["items"]) == 0


def test_videos_query_search(auth_client, seed_data, app):
    """Prueba que los videos puedan ser buscados/filtrados por título o canal."""
    fake_gateway = FakeYouTubeGateway()
    service = VideoService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        service.sync_videos(conn)
        conn.close()

    # Buscar por coincidencia exacta en título ("Video 1")
    resp_v1 = auth_client.get("/api/v1/videos?view=feed&query=Video 1")
    assert resp_v1.status_code == 200
    data_v1 = json.loads(resp_v1.data)
    assert len(data_v1["items"]) == 1
    assert data_v1["items"][0]["title"] == "Video 1"

    # Buscar por canal ("Canal A" -> debe traer Video 1 y Video 2, pero no Video 3)
    resp_ch = auth_client.get("/api/v1/videos?view=feed&query=Canal A")
    assert resp_ch.status_code == 200
    data_ch = json.loads(resp_ch.data)
    assert len(data_ch["items"]) == 2
    assert {v["youtubeVideoId"] for v in data_ch["items"]} == {"vid_1", "vid_2"}

    # Buscar coincidencia inexistente
    resp_none = auth_client.get("/api/v1/videos?view=feed&query=no_match_query")
    assert resp_none.status_code == 200
    data_none = json.loads(resp_none.data)
    assert len(data_none["items"]) == 0


def test_videos_shorts_filtering(auth_client, seed_data, app):
    """Prueba que los videos cortos (<= 180s) se filtren del feed."""
    fake_gateway = FakeYouTubeGateway()

    # Agregar un video corto (120 segundos)
    fake_gateway.playlist_items["UU_A"]["items"].append({
        "youtube_video_id": "vid_short",
        "title": "Video Corto",
        "description": "Short description",
        "published_at": "2026-07-30T11:00:00Z",
        "thumbnail_url": "t_short"
    })
    fake_gateway.video_details.append({
        "youtube_video_id": "vid_short",
        "duration_seconds": 120,
        "content_type": "video"
    })

    service = VideoService(gateway=fake_gateway)

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        service.sync_videos(conn)
        conn.close()

    # Obtener el feed
    resp = auth_client.get("/api/v1/videos?view=feed")
    assert resp.status_code == 200
    data = json.loads(resp.data)

    # Debe traer vid_1 y vid_2, pero NO vid_short
    items = data["items"]
    video_ids = [v["youtubeVideoId"] for v in items]

    assert "vid_1" in video_ids
    assert "vid_2" in video_ids
    assert "vid_short" not in video_ids


def test_videos_performance(auth_client, seed_data, app):
    """Prueba de rendimiento con 500 canales y 20.000 videos sintéticos (RF-13)."""
    import time

    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])

        # Limpiar categorías previas para evitar conflictos UNIQUE
        conn.execute("DELETE FROM channel_categories")

        # 1. Crear 500 canales
        channels_tuples = []
        for i in range(1, 501):
            channels_tuples.append((
                f"UC_CHAN_{i}", f"Canal {i}", f"Descripción del canal {i}",
                f"thumb_{i}", f"UU_CHAN_{i}", 1, 0, 0, "now", "now"
            ))

        conn.executemany("""
            INSERT INTO channels (
                youtube_channel_id, title, description, thumbnail_url,
                uploads_playlist_id, is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, channels_tuples)

        # Vincular la mitad de los canales a categoría 1
        conn.execute("""
            INSERT INTO channel_categories (channel_id, category_id, source, created_at)
            SELECT id, 1, 'manual', 'now' FROM channels WHERE id <= 250
        """)

        # 2. Crear 20.000 videos (40 por canal)
        channels_in_db = conn.execute("SELECT id FROM channels").fetchall()
        videos_tuples = []
        video_counter = 1
        for ch_row in channels_in_db:
            ch_id = ch_row["id"]
            for v_idx in range(1, 41):
                # Usar fechas ordenables
                pub_date = f"2026-07-29T10:{v_idx:02d}:00Z"
                videos_tuples.append((
                    f"vid_sint_{video_counter}", ch_id, f"Video sintético {video_counter}",
                    f"Desc video {video_counter}", pub_date, 300, f"thumb_v_{video_counter}",
                    "video", "now", "now"
                ))
                video_counter += 1

        conn.executemany("""
            INSERT INTO videos (
                youtube_video_id, channel_id, title, description, published_at,
                duration_seconds, thumbnail_url, content_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, videos_tuples)

        conn.commit()
        conn.close()

    # 3. Medir tiempo de respuesta para la primera página del feed (vista feed)
    start_time = time.perf_counter()
    resp_feed = auth_client.get("/api/v1/videos?view=feed&categoryId=1&limit=30")
    duration_feed = time.perf_counter() - start_time
    assert resp_feed.status_code == 200
    assert duration_feed < 0.5  # Menos de 500 ms de presupuesto

    # 4. Medir tiempo de respuesta para la primera página por canal (vista channels)
    start_time_chan = time.perf_counter()
    resp_chan = auth_client.get("/api/v1/videos?view=channels&categoryId=1&limit=30")
    duration_chan = time.perf_counter() - start_time_chan
    assert resp_chan.status_code == 200
    assert duration_chan < 0.5  # Menos de 500 ms de presupuesto

