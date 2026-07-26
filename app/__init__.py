import os

from flask import Flask

from app.config import get_config
from app.db import init_app as init_db
from app.migrator import run_migrations


def create_app(config_name=None):
    """Fábrica de la aplicación Flask."""
    app = Flask(__name__, instance_relative_config=True)

    # Obtener configuración
    config_class = get_config(config_name)
    app.config.from_object(config_class)

    # Asegurar que la carpeta instance existe si es necesaria
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Inicializar Base de Datos (ciclo de vida de conexión)
    init_db(app)

    # Si estamos en modo testing o desarrollo, correr migraciones automáticamente
    if app.config["TESTING"] or app.config.get("DEBUG"):
        # En memoria o local, ejecutar migraciones
        db_path = app.config["DATABASE_PATH"]
        # Asegurar directorio de la base de datos si no es en memoria
        if db_path != ":memory:":
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
        run_migrations(db_path)

    # Registrar Blueprints
    from app.api.health import health_bp
    from app.api.stubs import stubs_bp
    # Registramos con el prefijo /api/v1 como especifica openapi.yaml
    app.register_blueprint(health_bp, url_prefix="/api/v1")
    app.register_blueprint(stubs_bp, url_prefix="/api/v1")

    # Ruta base / que sirve el frontend
    @app.route("/")
    def index():
        from flask import render_template
        return render_template("base.html")

    return app
