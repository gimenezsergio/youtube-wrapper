
import pytest

from app import create_app
from app.db import get_db_connection


@pytest.fixture
def app():
    """Fixture que crea y configura una instancia de la aplicación para pruebas."""
    # Usar configuración de testing con base de datos en memoria por defecto
    app = create_app("testing")

    yield app

@pytest.fixture
def client(app):
    """Fixture que provee un cliente de pruebas para simular llamadas HTTP."""
    return app.test_client()

@pytest.fixture
def db(app):
    """Fixture que provee una conexión directa a la base de datos de pruebas configurada."""
    with app.app_context():
        # Obtener conexión a la base de datos de testing configurada (normalmente :memory:)
        conn = get_db_connection(app.config["DATABASE_PATH"])
        yield conn
        conn.close()
