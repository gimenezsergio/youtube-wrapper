import json


def test_health_endpoint(client):
    """Prueba que el endpoint /api/v1/health responda exitosamente."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data == {"status": "ok"}


def test_application_honors_reverse_proxy_prefix(client):
    response = client.get("/", headers={"X-Forwarded-Prefix": "/youtube-curator"})

    assert response.status_code == 200
    assert b'/youtube-curator/static/css/styles.css' in response.data
    assert b'/youtube-curator/api/v1/auth/login' in response.data
    assert b'crossorigin="use-credentials"' in response.data
    assert b'window.__APP_BASE_PATH__ = "/youtube-curator"' in response.data
