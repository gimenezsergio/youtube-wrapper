import os
import tempfile

import pytest

from app import create_app
from app.db import get_db_connection
from app.migrator import run_migrations


@pytest.fixture
def app():
    """Fixture que crea y configura una instancia de la aplicación para pruebas con una BD temporal."""
    # Crear un archivo temporal para la base de datos de pruebas
    db_fd, db_path = tempfile.mkstemp()

    # Crear la aplicación en modo testing
    app = create_app("testing")
    app.config["DATABASE_PATH"] = db_path

    # Ejecutar las migraciones en la base de datos temporal física
    with app.app_context():
        run_migrations(db_path)

    yield app

    # Limpieza del archivo temporal al finalizar la prueba
    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass

@pytest.fixture
def client(app):
    """Fixture que provee un cliente de pruebas para simular llamadas HTTP."""
    return app.test_client()

@pytest.fixture
def db(app):
    """Fixture que provee una conexión directa a la base de datos de pruebas temporal."""
    with app.app_context():
        conn = get_db_connection(app.config["DATABASE_PATH"])
        yield conn
        conn.close()
