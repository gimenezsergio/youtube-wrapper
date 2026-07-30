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

@pytest.fixture
def seed_data(app):
    """Carga categorías y canales para probar clasificación."""
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        # Insertar 2 categorías
        conn.execute("""
            INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
            VALUES (1, 'Tech', 'tech', 1, 'now', 'now')
        """)
        conn.execute("""
            INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
            VALUES (2, 'Cooking', 'cooking', 2, 'now', 'now')
        """)
        # Insertar canal
        conn.execute("""
            INSERT INTO channels (
                id, youtube_channel_id, title, description, thumbnail_url,
                is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
            ) VALUES (10, 'UC_XYZ', 'Canal Pruebas', 'Un canal', 'thumb', 1, 0, 0, 'now', 'now')
        """)
        conn.commit()
        conn.close()

def test_class_01_anonymous_blocked(client):
    """Las peticiones anónimas a la clasificación de canales retornan 401 o 403."""
    response = client.put("/api/v1/channels/10/categories", json={"categoryIds": [1, 2]})
    assert response.status_code in [401, 403]

def test_class_02_assign_categories(auth_client, seed_data, app):
    """Asignar categorías agrega registros en channel_categories e incluye en classification_decisions."""
    payload = {"categoryIds": [1, 2]}
    response = auth_client.put("/api/v1/channels/10/categories", json=payload)
    assert response.status_code == 200

    data = json.loads(response.data)
    assert set(data["categoryIds"]) == {1, 2}

    # Verificar base de datos
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])

        # Debe haber 2 asignaciones manuales
        cc_rows = conn.execute("SELECT category_id, source FROM channel_categories WHERE channel_id = 10").fetchall()
        assert len(cc_rows) == 2
        for r in cc_rows:
            assert r["source"] == "manual"

        # Debe haber 2 decisiones de inclusión ('include')
        dec_rows = conn.execute("""
            SELECT category_id, decision
            FROM classification_decisions
            WHERE channel_id = 10
        """).fetchall()
        assert len(dec_rows) == 2
        for r in dec_rows:
            assert r["decision"] == "include"

        conn.close()

def test_class_03_remove_categories(auth_client, seed_data, app):
    """Quitar una categoría remueve de channel_categories y registra una exclusión ('exclude')."""
    # 1. Asignar 1 y 2
    auth_client.put("/api/v1/channels/10/categories", json={"categoryIds": [1, 2]})

    # 2. Quitar 1 (asignar solo 2)
    response = auth_client.put("/api/v1/channels/10/categories", json={"categoryIds": [2]})
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data["categoryIds"] == [2]

    # 3. Verificar base de datos
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])

        # Solo la categoría 2 permanece asignada
        cc_rows = conn.execute("SELECT category_id FROM channel_categories WHERE channel_id = 10").fetchall()
        assert len(cc_rows) == 1
        assert cc_rows[0]["category_id"] == 2

        # Decisiones: categoría 1 es 'exclude', categoría 2 es 'include'
        dec_rows = conn.execute("""
            SELECT category_id, decision
            FROM classification_decisions
            WHERE channel_id = 10
        """).fetchall()
        assert len(dec_rows) == 2

        dec_1 = next(r for r in dec_rows if r["category_id"] == 1)
        assert dec_1["decision"] == "exclude"

        dec_2 = next(r for r in dec_rows if r["category_id"] == 2)
        assert dec_2["decision"] == "include"

        conn.close()

def test_class_04_nonexistent_category_error(auth_client, seed_data):
    """Intentar clasificar con una categoría inexistente retorna 400."""
    response = auth_client.put("/api/v1/channels/10/categories", json={"categoryIds": [999]})
    assert response.status_code == 400
