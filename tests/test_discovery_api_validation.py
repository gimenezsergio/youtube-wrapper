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
    r1 = auth_client.get("/api/v1/discoveries?cursor=abc")
    assert r1.status_code == 400
    assert r1.get_json()["error"]["code"] == "VALIDATION_ERROR"

    r2 = auth_client.get("/api/v1/discoveries?band=nonsense")
    assert r2.status_code == 400
    assert r2.get_json()["error"]["code"] == "VALIDATION_ERROR"

    r3 = auth_client.get("/api/v1/discoveries?limit=0")
    assert r3.status_code == 400

    r4 = auth_client.get("/api/v1/discoveries?limit=101")
    assert r4.status_code == 400


def test_corr_api_02_feedback_validation(auth_client, app):
    """CORR-API-02 — Feedback inválido devuelve 422."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        db.execute(
            "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
            "VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')"
        )
        db.execute(
            "INSERT INTO channels (id, youtube_channel_id, title, created_at, updated_at) "
            "VALUES (10, 'UC_OLD', 'Canal Viejo', 'now', 'now')"
        )
        db.execute(
            "INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, "
            "duration_seconds, created_at, updated_at) "
            "VALUES (20, 'vid_old', 10, 'Video Viejo', '2026-07-20T10:00:00Z', 500, 'now', 'now')"
        )
        db.commit()
        db.close()

    # Acción desconocida
    r1 = auth_client.post("/api/v1/discoveries/20/feedback", json={"categoryId": 1, "action": "invented"})
    assert r1.status_code == 422
    assert r1.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # Falta categoryId
    r2 = auth_client.post("/api/v1/discoveries/20/feedback", json={"action": "more_like_this"})
    assert r2.status_code == 422

    # categoryId no entero
    r3 = auth_client.post("/api/v1/discoveries/20/feedback", json={"categoryId": "abc", "action": "more_like_this"})
    assert r3.status_code == 422

    # propiedad channelId enviada (prohibida por especificación)
    r4 = auth_client.post(
        "/api/v1/discoveries/20/feedback", json={"categoryId": 1, "action": "more_like_this", "channelId": 10}
    )
    assert r4.status_code == 422


def test_corr_api_03_non_existent_resources(auth_client, app):
    """CORR-API-03 — Recursos inexistentes devuelven 404."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        db.execute(
            "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
            "VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')"
        )
        db.commit()
        db.close()

    # feedback sobre video inexistente
    r1 = auth_client.post("/api/v1/discoveries/999/feedback", json={"categoryId": 1, "action": "more_like_this"})
    assert r1.status_code == 404
    assert r1.get_json()["error"]["code"] == "NOT_FOUND"

    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        db.execute(
            "INSERT INTO channels (id, youtube_channel_id, title, created_at, updated_at) "
            "VALUES (10, 'UC_OLD', 'Canal Viejo', 'now', 'now')"
        )
        db.execute(
            "INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, "
            "duration_seconds, created_at, updated_at) "
            "VALUES (20, 'vid_old', 10, 'Video Viejo', '2026-07-20T10:00:00Z', 500, 'now', 'now')"
        )
        db.commit()
        db.close()

    # feedback en categoria inexistente
    r2 = auth_client.post("/api/v1/discoveries/20/feedback", json={"categoryId": 999, "action": "more_like_this"})
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


def test_corr_api_04_context_validation(auth_client, app):
    """CORR-API-04 — Validación de contexto de candidato y categoría."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        db.execute(
            "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
            "VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')"
        )
        db.execute(
            "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
            "VALUES (2, 'Cat B', 'cat-b', 2, 'now', 'now')"
        )
        db.execute(
            "INSERT INTO channels (id, youtube_channel_id, title, created_at, updated_at) "
            "VALUES (10, 'UC_OLD', 'Canal Viejo', 'now', 'now')"
        )
        db.execute(
            "INSERT INTO videos (id, youtube_video_id, channel_id, title, published_at, "
            "duration_seconds, created_at, updated_at) "
            "VALUES (20, 'vid_old', 10, 'Video Viejo', '2026-07-20T10:00:00Z', 500, 'now', 'now')"
        )
        # Candidato asociado únicamente a la Categoría 1
        db.execute("""
            INSERT INTO discovery_candidates (
                category_id, video_id, score, band, reasons_json, status,
                last_refresh_run_id, selection_rank, first_seen_at, last_seen_at
            ) VALUES (
                1, 20, 85.0, 'related', '[]', 'active', NULL, 1, 'now', 'now'
            )
        """)
        db.commit()
        db.close()

    # Feedback para Video 20 en Categoría 2 (no es candidato en Cat 2) -> 404
    r1 = auth_client.post("/api/v1/discoveries/20/feedback", json={"categoryId": 2, "action": "more_like_this"})
    assert r1.status_code == 404
    assert "Candidato de descubrimiento no encontrado" in r1.get_json()["error"]["message"]

    # Feedback para Video 20 en Categoría 1 (candidato válido) -> 200
    r2 = auth_client.post("/api/v1/discoveries/20/feedback", json={"categoryId": 1, "action": "more_like_this"})
    assert r2.status_code == 200
    assert r2.get_json()["applied"] is True


def test_corr_api_05_exploration_topics_validation(auth_client, app):
    """CORR-API-05 — Validación de endpoints de temas de exploración."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        db.execute(
            "INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at) "
            "VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')"
        )
        db.commit()
        db.close()

    # GET con estado inválido -> 400
    r1 = auth_client.get("/api/v1/categories/1/exploration-topics?status=invalid_status")
    assert r1.status_code == 400

    # POST término vacío -> 422
    r2 = auth_client.post("/api/v1/categories/1/exploration-topics", json={"term": ""})
    assert r2.status_code == 422

    # POST peso fuera de rango -> 422
    r3 = auth_client.post("/api/v1/categories/1/exploration-topics", json={"term": "Valid", "weight": 15.0})
    assert r3.status_code == 422

    # PATCH estado inválido -> 422
    r4 = auth_client.patch(
        "/api/v1/categories/1/exploration-topics/1", json={"status": "invalid_status"}
    )
    assert r4.status_code == 422


def test_corr_api_06_refresh_runs_limit(auth_client, app):
    """CORR-API-06 — GET /refresh-runs respeta el parámetro limit."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        for i in range(1, 10):
            db.execute(
                "INSERT INTO refresh_runs "
                "(id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json) "
                "VALUES (?, 'succeeded', '[\"discovery\"]', NULL, 'now', '{}', '[]')",
                (i,),
            )
        db.commit()
        db.close()

    # Limit inválido -> 400
    r1 = auth_client.get("/api/v1/refresh-runs?limit=0")
    assert r1.status_code == 400

    r2 = auth_client.get("/api/v1/refresh-runs?limit=101")
    assert r2.status_code == 400

    # Limit válido -> 200 respetando límite
    r3 = auth_client.get("/api/v1/refresh-runs?limit=3")
    assert r3.status_code == 200
    items = r3.get_json()["items"]
    assert len(items) == 3


def test_corr_api_07_refresh_run_serialization(auth_client, app):
    """CORR-API-07 — Serialización camelCase y sanitizada de RefreshRun."""
    counters_dict = {
        "subscriptions": {"created": 1, "updated": 2},
        "followed_videos": {"created": 5, "processedChannels": 3},
        "discovery": {
            "searches_executed": 4,
            "quota_exhausted": False,
            "categories": {"1": {"selected": 8, "shortfall": None}},
        },
    }
    errors_list = [
        {
            "stage": "discovery",
            "category_id": 1,
            "code": "YOUTUBE_TIMEOUT",
            "message": "YouTube no respondió a tiempo.",
        }
    ]

    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        db.execute(
            "INSERT INTO refresh_runs "
            "(id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json) "
            "VALUES (10, 'partial', '[\"subscriptions\",\"followed_videos\",\"discovery\"]', "
            "NULL, '2026-08-01T10:00:00Z', ?, ?)",
            (json.dumps(counters_dict), json.dumps(errors_list)),
        )
        db.commit()
        db.close()

    r = auth_client.get("/api/v1/refresh-runs/10")
    assert r.status_code == 200
    data = r.get_json()

    assert data["id"] == 10
    assert data["status"] == "partial"
    assert data["stages"] == ["subscriptions", "followed_videos", "discovery"]

    # Verificación de camelCase en counters
    counters = data["counters"]
    assert "followedVideos" in counters
    assert "followed_videos" not in counters
    assert counters["discovery"]["searchesExecuted"] == 4
    assert counters["discovery"]["quotaExhausted"] is False

    # Verificación de errors
    errors = data["errors"]
    assert len(errors) == 1
    assert errors[0]["stage"] == "discovery"
    assert errors[0]["categoryId"] == 1
    assert errors[0]["code"] == "YOUTUBE_TIMEOUT"
    assert errors[0]["message"] == "YouTube no respondió a tiempo."


def test_corr_api_08_unified_stages(auth_client):
    """CORR-API-08 — Etapas unificadas (subscriptions, followed_videos, discovery)."""
    # Etapas no habilitadas -> 422
    r1 = auth_client.post("/api/v1/refresh-runs", json={"stages": ["channels"]})
    assert r1.status_code == 422

    r2 = auth_client.post("/api/v1/refresh-runs", json={"stages": ["classification"]})
    assert r2.status_code == 422

    # Etapas válidas -> 202
    r3 = auth_client.post(
        "/api/v1/refresh-runs", json={"stages": ["subscriptions", "followed_videos", "discovery"]}
    )
    assert r3.status_code == 202
    data = r3.get_json()
    assert data["stages"] == ["subscriptions", "followed_videos", "discovery"]
