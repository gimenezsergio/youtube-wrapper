import json

import pytest

from app.db import get_db_connection


# Helper para autenticar sesión
@pytest.fixture
def auth_client(client):
    """Cliente de pruebas con sesión de propietario iniciada."""
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"
        sess["csrf_token"] = "mock-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "mock-csrf-token"
    return client

def test_cat_01_create_category(auth_client, app):
    """CAT-01: Se crea una categoría correctamente con su posición secuencial."""
    payload = {
        "name": "Fotografía",
        "description": "Reviews de cámaras y lentes",
        "keywords": [
            {"term": "Sony A7", "polarity": "positive", "weight": 2.5},
            {"term": "Shorts", "polarity": "negative", "weight": 1.0}
        ]
    }

    response = auth_client.post("/api/v1/categories", json=payload)
    assert response.status_code == 201
    data = json.loads(response.data)

    assert data["id"] is not None
    assert data["name"] == "Fotografía"
    assert data["description"] == "Reviews de cámaras y lentes"
    assert data["position"] == 1
    assert len(data["keywords"]) == 2
    assert data["keywords"][0]["term"] == "Sony A7"
    assert data["keywords"][0]["polarity"] == "positive"
    assert data["keywords"][0]["weight"] == 2.5

def test_cat_02_duplicate_name_conflict(auth_client):
    """CAT-02: Conflicto 409 al intentar crear una categoría con nombre duplicado (case-insensitive)."""
    payload_1 = {"name": "Fotografía"}
    response = auth_client.post("/api/v1/categories", json=payload_1)
    assert response.status_code == 201

    # Duplicado con diferencias de mayúsculas/minúsculas y espacios
    payload_2 = {"name": "  fotografía  "}
    response = auth_client.post("/api/v1/categories", json=payload_2)
    assert response.status_code == 409
    data = json.loads(response.data)
    assert data["error"]["code"] == "DUPLICATE_CATEGORY"

def test_cat_03_update_category(auth_client):
    """CAT-03: Editar una categoría y sus palabras clave funciona e invalida las antiguas."""
    # 1. Crear
    create_resp = auth_client.post("/api/v1/categories", json={
        "name": "Cocina",
        "keywords": [{"term": "receta", "polarity": "positive"}]
    })
    cat_id = json.loads(create_resp.data)["id"]

    # 2. Modificar
    payload = {
        "name": "Cocina Gourmet",
        "description": "Recetas premium",
        "keywords": [
            {"term": "pasta", "polarity": "positive", "weight": 3.0},
            {"term": "postres", "polarity": "positive", "weight": 1.5}
        ]
    }
    response = auth_client.put(f"/api/v1/categories/{cat_id}", json=payload)
    assert response.status_code == 200
    data = json.loads(response.data)

    assert data["name"] == "Cocina Gourmet"
    assert data["description"] == "Recetas premium"
    assert len(data["keywords"]) == 2
    # El término anterior "receta" debe haber sido eliminado
    terms = [k["term"] for k in data["keywords"]]
    assert "receta" not in terms
    assert "pasta" in terms
    assert "postres" in terms

def test_cat_04_delete_category(auth_client, app):
    """CAT-04: Eliminar una categoría limpia relaciones en cascada en la DB."""
    # Crear
    create_resp = auth_client.post("/api/v1/categories", json={
        "name": "Música",
        "keywords": [{"term": "guitarra", "polarity": "positive"}]
    })
    cat_id = json.loads(create_resp.data)["id"]

    # Eliminar
    response = auth_client.delete(f"/api/v1/categories/{cat_id}")
    assert response.status_code == 204

    # Verificar limpieza
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        # No debe haber categoría
        cursor = conn.execute("SELECT COUNT(*) as count FROM categories WHERE id = ?", (cat_id,))
        assert cursor.fetchone()["count"] == 0
        # No debe haber keywords
        cursor = conn.execute("SELECT COUNT(*) as count FROM category_keywords WHERE category_id = ?", (cat_id,))
        assert cursor.fetchone()["count"] == 0
        conn.close()

def test_cat_05_reorder_categories(auth_client, app):
    """CAT-05: Reordenar categorías persiste las nuevas posiciones consecutivas."""
    # Crear 3 categorías
    cat1_id = json.loads(auth_client.post("/api/v1/categories", json={"name": "A"}).data)["id"]
    cat2_id = json.loads(auth_client.post("/api/v1/categories", json={"name": "B"}).data)["id"]
    cat3_id = json.loads(auth_client.post("/api/v1/categories", json={"name": "C"}).data)["id"]

    # Enviar reordenamiento: C(1), A(2), B(3)
    reorder_payload = {"categoryIds": [cat3_id, cat1_id, cat2_id]}
    response = auth_client.put("/api/v1/categories/reorder", json=reorder_payload)
    assert response.status_code == 204

    # Verificar en base de datos
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])

        cursor = conn.execute("SELECT id, position FROM categories ORDER BY position ASC")
        rows = cursor.fetchall()

        assert rows[0]["id"] == cat3_id
        assert rows[0]["position"] == 1

        assert rows[1]["id"] == cat1_id
        assert rows[1]["position"] == 2

        assert rows[2]["id"] == cat2_id
        assert rows[2]["position"] == 3

        conn.close()

def test_cat_06_keywords_validation(auth_client):
    """CAT-06: Validaciones de campos de keywords incorrectos."""
    # Intentar peso fuera de rango (0..10)
    payload = {
        "name": "Videojuegos",
        "keywords": [{"term": "Zelda", "polarity": "positive", "weight": 15.0}]
    }
    response = auth_client.post("/api/v1/categories", json=payload)
    assert response.status_code == 422
    data = json.loads(response.data)
    assert "keywords.0.weight" in data["error"]["details"]

    # Intentar polaridad incorrecta
    payload = {
        "name": "Videojuegos",
        "keywords": [{"term": "Zelda", "polarity": "neutral"}]
    }
    response = auth_client.post("/api/v1/categories", json=payload)
    assert response.status_code == 422
