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
def seed_channels(app):
    """Carga de canales de prueba en la base de datos."""
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        # Insertar categorías
        conn.execute("""
            INSERT INTO categories (name, normalized_name, position, created_at, updated_at)
            VALUES ('Ciencia', 'ciencia', 1, 'now', 'now')
        """)
        conn.execute("""
            INSERT INTO categories (name, normalized_name, position, created_at, updated_at)
            VALUES ('Cocina', 'cocina', 2, 'now', 'now')
        """)

        cat_ciencia = conn.execute("SELECT id FROM categories WHERE name = 'Ciencia'").fetchone()["id"]
        cat_cocina = conn.execute("SELECT id FROM categories WHERE name = 'Cocina'").fetchone()["id"]

        # Insertar canales
        conn.execute("""
            INSERT INTO channels (
                id, youtube_channel_id, title, description, thumbnail_url,
                is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
            ) VALUES (1, 'UC_1', 'La Ciencia Detrás', 'Canal de física', 'url1', 1, 0, 0, 'now', 'now')
        """)
        conn.execute("""
            INSERT INTO channels (
                id, youtube_channel_id, title, description, thumbnail_url,
                is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
            ) VALUES (2, 'UC_2', 'Recetas Rápidas', 'Platos en 5 minutos', 'url2', 1, 0, 0, 'now', 'now')
        """)
        conn.execute("""
            INSERT INTO channels (
                id, youtube_channel_id, title, description, thumbnail_url,
                is_subscribed, is_locally_followed, is_blocked, created_at, updated_at
            ) VALUES (3, 'UC_3', 'Canal Abandonado', 'Vlogs viejos', 'url3', 0, 0, 0, 'now', 'now')
        """)

        # Asignar categorías
        conn.execute("""
            INSERT INTO channel_categories (channel_id, category_id, source, created_at)
            VALUES (1, ?, 'manual', 'now')
        """, (cat_ciencia,))
        conn.execute("""
            INSERT INTO channel_categories (channel_id, category_id, source, created_at)
            VALUES (2, ?, 'manual', 'now')
        """, (cat_cocina,))

        conn.commit()
        conn.close()

        return {
            "cat_ciencia": cat_ciencia,
            "cat_cocina": cat_cocina
        }

def test_channels_01_anonymous_blocked(client):
    """Las peticiones anónimas a endpoints de canales retornan 401."""
    response = client.get("/api/v1/channels")
    assert response.status_code == 401

def test_channels_02_list_all(auth_client, seed_channels):
    """Obtener listado de canales completo con paginación."""
    response = auth_client.get("/api/v1/channels?limit=2")
    assert response.status_code == 200
    data = json.loads(response.data)

    assert "items" in data
    assert len(data["items"]) == 2
    assert data["nextCursor"] == "2"

def test_channels_03_filter_query(auth_client, seed_channels):
    """Buscar por texto en título."""
    response = auth_client.get("/api/v1/channels?query=Ciencia")
    assert response.status_code == 200
    data = json.loads(response.data)

    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "La Ciencia Detrás"

def test_channels_04_filter_unclassified(auth_client, seed_channels):
    """Filtrar canales sin clasificar."""
    response = auth_client.get("/api/v1/channels?unclassified=true")
    assert response.status_code == 200
    data = json.loads(response.data)

    # El canal 3 no tiene categoría asignada
    assert len(data["items"]) == 1
    assert data["items"][0]["youtubeChannelId"] == "UC_3"

def test_channels_05_filter_category(auth_client, seed_channels):
    """Filtrar canales pertenecientes a una categoría específica."""
    cat_id = seed_channels["cat_cocina"]
    response = auth_client.get(f"/api/v1/channels?categoryId={cat_id}")
    assert response.status_code == 200
    data = json.loads(response.data)

    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Recetas Rápidas"

def test_channels_06_block_toggle(auth_client, seed_channels):
    """Bloquear y desbloquear un canal correctamente."""
    # 1. Bloquear
    response = auth_client.put("/api/v1/channels/1/block", json={"blocked": True})
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["blocked"] is True

    # 2. Desbloquear
    response = auth_client.put("/api/v1/channels/1/block", json={"blocked": False})
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["blocked"] is False

def test_channels_07_block_validation(auth_client, seed_channels):
    """Valida los campos obligatorios al bloquear."""
    response = auth_client.put("/api/v1/channels/1/block", json={})
    assert response.status_code == 422
