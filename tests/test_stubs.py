import json


def test_auth_status_stub(client):
    """Prueba que el endpoint stub /api/v1/auth/status retorne no autenticado."""
    response = client.get("/api/v1/auth/status")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["authenticated"] is False
    assert data["email"] is None

def test_categories_stub(client):
    """Prueba que el endpoint stub /api/v1/categories retorne las categorías mock de Fase 0."""
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"

    response = client.get("/api/v1/categories")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "items" in data
    assert len(data["items"]) == 2
    assert data["items"][0]["name"] == "Tecnología"
    assert data["items"][1]["name"] == "Fotografía"
