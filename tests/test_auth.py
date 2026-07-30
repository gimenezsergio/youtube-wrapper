import json
from unittest.mock import Mock, patch

from app.auth.encryption import decrypt_token
from app.db import get_db_connection


def test_auth_01_protected_route_anonymous(client):
    """AUTH-01: Un visitante sin sesión recibe 401 en rutas protegidas de la API."""
    response = client.get("/api/v1/categories")
    assert response.status_code == 401
    data = json.loads(response.data)
    assert data["error"]["code"] == "UNAUTHORIZED"

def test_auth_04_callback_invalid_state(client):
    """AUTH-04: El callback sin state o con state incorrecto debe fallar."""
    # Caso 1: Callback sin haber iniciado login (sin state en session)
    response = client.get("/api/v1/auth/callback?code=mock-code&state=some-state")
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data["error"]["code"] == "INVALID_STATE"

    # Caso 2: State diferente al almacenado en sesión
    with client.session_transaction() as sess:
        sess["oauth_state"] = "correct-state"

    response = client.get("/api/v1/auth/callback?code=mock-code&state=wrong-state")
    assert response.status_code == 400
    data = json.loads(response.data)
    assert data["error"]["code"] == "INVALID_STATE"

@patch("requests.post")
@patch("requests.get")
def test_auth_02_propietario_valido(mock_get, mock_post, app, client):
    """AUTH-02: Callback con propietario válido almacena credenciales cifradas y rota sesión."""
    # Configurar mock para el intercambio de tokens
    mock_post_resp = Mock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "access_token": "secret-access-token-123",
        "refresh_token": "secret-refresh-token-456",
        "expires_in": 3600
    }
    mock_post.return_value = mock_post_resp

    # Configurar mock para la obtención de info del propietario
    mock_get_resp = Mock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {
        "email": "test_owner@gmail.com" # Debe coincidir con TestingConfig
    }
    mock_get.return_value = mock_get_resp

    # Guardar state correcto en la sesión
    with client.session_transaction() as sess:
        sess["oauth_state"] = "correct-state"

    response = client.get("/api/v1/auth/callback?code=mock-code&state=correct-state")

    # Debe redirigir al root
    assert response.status_code == 302
    assert response.location == "/"

    # Verificar sesión activa del propietario
    with client.session_transaction() as sess:
        assert sess.get("authenticated") is True
        assert sess.get("email") == "test_owner@gmail.com"
        assert "csrf_token" in sess

    # Verificar persistencia en base de datos cifrada (Task 1.9)
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        cursor = conn.execute("SELECT access_token, refresh_token FROM credentials LIMIT 1")
        row = cursor.fetchone()
        assert row is not None

        # El token NO debe estar en texto plano en la base de datos
        assert row["access_token"] != "secret-access-token-123"
        assert row["refresh_token"] != "secret-refresh-token-456"

        # Pero al descifrarlo debe ser idéntico
        assert decrypt_token(row["access_token"]) == "secret-access-token-123"
        assert decrypt_token(row["refresh_token"]) == "secret-refresh-token-456"
        conn.close()

@patch("requests.post")
@patch("requests.get")
def test_auth_03_usuario_no_permitido(mock_get, mock_post, app, client):
    """AUTH-03: Callback con correo de Google diferente al propietario debe ser rechazado."""
    # Configurar mock para el intercambio de tokens
    mock_post_resp = Mock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "access_token": "some-token",
        "expires_in": 3600
    }
    mock_post.return_value = mock_post_resp

    # Configurar mock de email no autorizado
    mock_get_resp = Mock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {
        "email": "intruder@gmail.com"
    }
    mock_get.return_value = mock_get_resp

    # Guardar state
    with client.session_transaction() as sess:
        sess["oauth_state"] = "correct-state"

    response = client.get("/api/v1/auth/callback?code=mock-code&state=correct-state")

    # Debe ser denegado con 403 Forbidden
    assert response.status_code == 403
    data = json.loads(response.data)
    assert data["error"]["code"] == "ACCESS_DENIED"

    # Verificar que no se guardaron credenciales en la DB
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        cursor = conn.execute("SELECT COUNT(*) as count FROM credentials")
        assert cursor.fetchone()["count"] == 0
        conn.close()

def test_auth_05_csrf_protection(client):
    """AUTH-05: Una mutación (POST/PUT/DELETE) requiere validación CSRF correcta."""
    # 1. Simular inicio de sesión activo
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"
        sess["csrf_token"] = "valid-csrf-token"

    # 2. Mutación (logout es POST) sin cabecera CSRF: debe dar 403
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 403
    data = json.loads(response.data)
    assert data["error"]["code"] == "INVALID_CSRF_TOKEN"

    # 3. Mutación con cabecera CSRF incorrecta: debe dar 403
    headers = {"X-CSRF-Token": "invalid-token"}
    response = client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 403

    # 4. Mutación con cabecera CSRF correcta: debe procesarse con éxito (204)
    headers = {"X-CSRF-Token": "valid-csrf-token"}
    response = client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204

    # Y la sesión del servidor debe quedar vacía (cerrada)
    with client.session_transaction() as sess:
        assert not sess.get("authenticated")
        assert "csrf_token" not in sess
