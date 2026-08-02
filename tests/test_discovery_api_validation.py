import json
import pytest
from app.db import get_db_connection

@pytest.fixture
def auth_client(client):
    """Cliente de pruebas con sesión de propietario iniciada."""
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"
        sess["csrf_token"] = "mock-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "mock-csrf-token"
    return client

def test_corr_api_01_query_validation(auth_client):
    """CORR-API-01 — Query inválida devuelve 400."""
    # Cursor malformado
    r1 = auth_client.get("/api/v1/discoveries?cursor=abc")
    assert r1.status_code == 400
    
    # Banda desconocida
    r2 = auth_client.get("/api/v1/discoveries?band=nonsense")
    assert r2.status_code == 400

    # limit fuera de rango (0)
    r3 = auth_client.get("/api/v1/discoveries?limit=0")
    assert r3.status_code == 400

    # limit fuera de rango (101)
    r4 = auth_client.get("/api/v1/discoveries?limit=101")
    assert r4.status_code == 400


def test_corr_api_02_feedback_validation(auth_client, app):
    """CORR-API-02 — Feedback inválido devuelve 422."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        # Insertar categoria
        db.execute("INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')")
        # Canal y video
        db.execute("INSERT INTO channels (id, youtube_channel_id, title, created_at, updated_at) VALUES (10, 'UC_OLD', 'Canal Viejo', 'now', 'now')")
        db.execute("INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, duration_seconds, created_at, updated_at) VALUES (20, 'vid_old', 10, 'Video Viejo', '2026-07-20T10:00:00Z', 500, 'now', 'now')")
        db.commit()
        db.close()

    # Acción desconocida/inventada
    r1 = auth_client.post("/api/v1/discoveries/20/feedback", json={
        "categoryId": 1,
        "action": "invented"
    })
    assert r1.status_code == 422

    # Falta categoryId
    r2 = auth_client.post("/api/v1/discoveries/20/feedback", json={
        "action": "more_like_this"
    })
    assert r2.status_code == 422

    # categoryId no entero
    r3 = auth_client.post("/api/v1/discoveries/20/feedback", json={
        "categoryId": "abc",
        "action": "more_like_this"
    })
    assert r3.status_code == 422

    # propiedad channelId enviada (prohibido por especificación/diseño)
    r4 = auth_client.post("/api/v1/discoveries/20/feedback", json={
        "categoryId": 1,
        "action": "more_like_this",
        "channelId": 10
    })
    assert r4.status_code == 422


def test_corr_api_03_non_existent_resources(auth_client, app):
    """CORR-API-03 — Recursos inexistentes devuelven 404."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        # Insertar categoria
        db.execute("INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')")
        db.commit()
        db.close()

    # feedback sobre video inexistente
    r1 = auth_client.post("/api/v1/discoveries/999/feedback", json={
        "categoryId": 1,
        "action": "more_like_this"
    })
    assert r1.status_code == 404

    # feedback en categoria inexistente
    # (Video 20 existe, pero categoría 999 no existe)
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        db.execute("INSERT INTO channels (id, youtube_channel_id, title, created_at, updated_at) VALUES (10, 'UC_OLD', 'Canal Viejo', 'now', 'now')")
        db.execute("INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, duration_seconds, created_at, updated_at) VALUES (20, 'vid_old', 10, 'Video Viejo', '2026-07-20T10:00:00Z', 500, 'now', 'now')")
        db.commit()
        db.close()

    r2 = auth_client.post("/api/v1/discoveries/20/feedback", json={
        "categoryId": 999,
        "action": "more_like_this"
    })
    assert r2.status_code == 404

    # bloquear canal inexistente
    r3 = auth_client.put("/api/v1/channels/999/block", json={"blocked": True})
    assert r3.status_code == 404

    # restaurar ocultacion inexistente (video 999)
    r4 = auth_client.delete("/api/v1/discoveries/999/hidden?categoryId=1")
    assert r4.status_code == 404

    # modificar tema inexistente
    r5 = auth_client.patch("/api/v1/categories/1/exploration-topics/999", json={"weight": 5.0})
    assert r5.status_code == 404
