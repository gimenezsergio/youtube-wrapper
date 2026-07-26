import json


def test_health_endpoint(client):
    """Prueba que el endpoint /api/v1/health responda exitosamente."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data == {"status": "ok"}
