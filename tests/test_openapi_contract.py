import json

import pytest

from app.db import get_db_connection


@pytest.fixture
def auth_client(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"
        sess["csrf_token"] = "mock-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "mock-csrf-token"
    return client


def test_openapi_spec_file_exists_and_contains_schemas():
    """Verifica que el archivo specs/openapi.yaml existe y contiene esquemas clave."""
    with open("specs/openapi.yaml", "r", encoding="utf-8") as f:
        content = f.read()

    assert "openapi: 3.1.0" in content
    assert "Error:" in content
    assert "RefreshRun:" in content
    assert "DiscoveryRecommendation:" in content
    assert "/discoveries:" in content
    assert "/refresh-runs:" in content


def test_openapi_error_schema_compliance(auth_client):
    """Verifica que todas las respuestas de error 400 y 422 cumplan con la estructura de Error de OpenAPI."""
    r_400 = auth_client.get("/api/v1/discoveries?limit=invalid")
    assert r_400.status_code == 400
    data_400 = r_400.get_json()
    assert "error" in data_400
    assert "code" in data_400["error"]
    assert "message" in data_400["error"]

    r_422 = auth_client.post("/api/v1/discoveries/1/feedback", json={"action": "invalid"})
    assert r_422.status_code == 422
    data_422 = r_422.get_json()
    assert "error" in data_422
    assert "code" in data_422["error"]
    assert "message" in data_422["error"]


def test_openapi_refresh_run_schema_compliance(auth_client, app):
    """Verifica que la respuesta de GET /refresh-runs/<id> cumpla con el esquema RefreshRun de OpenAPI."""
    counters = {
        "subscriptions": {"created": 2},
        "followed_videos": {"created": 10},
        "discovery": {"searches_executed": 3, "quota_exhausted": False, "categories": {}},
    }
    errors = [{"stage": "discovery", "category_id": 1, "code": "ERR", "message": "msg"}]

    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        db.execute(
            "INSERT INTO refresh_runs "
            "(id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json) "
            "VALUES (1, 'succeeded', '[\"subscriptions\",\"followed_videos\",\"discovery\"]', "
            "NULL, '2026-08-01T10:00:00Z', ?, ?)",
            (json.dumps(counters), json.dumps(errors)),
        )
        db.commit()
        db.close()

    r = auth_client.get("/api/v1/refresh-runs/1")
    assert r.status_code == 200
    run = r.get_json()

    # Campos requeridos por OpenAPI RefreshRun
    required_fields = ["id", "status", "stages", "requestedAt", "counters", "errors"]
    for field in required_fields:
        assert field in run, f"Falta el campo obligatorio {field} en RefreshRun"

    # Claves camelCase en counters
    assert "followedVideos" in run["counters"]
    assert "searchesExecuted" in run["counters"]["discovery"]
