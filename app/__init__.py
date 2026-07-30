import os

from flask import Flask

from app.config import get_config
from app.db import init_app as init_db
from app.migrator import run_migrations


def csrf_protect():
    """Protección CSRF para mutaciones HTTP (Seguridad RNF-01)."""
    from flask import abort, jsonify, request, session
    if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
        header_token = request.headers.get("X-CSRF-Token")
        session_token = session.get("csrf_token")

        if not session_token or not header_token or header_token != session_token:
            if request.path.startswith("/api/"):
                return jsonify({
                    "error": {
                        "code": "INVALID_CSRF_TOKEN",
                        "message": "Acceso denegado: Token CSRF inválido o faltante."
                    }
                }), 403
            abort(403)

def check_auth():
    """Autenticación obligatoria para endpoints privados de la API."""
    from flask import jsonify, request, session
    if request.path.startswith("/api/v1/"):
        public_paths = [
            "/api/v1/health",
            "/api/v1/auth/login",
            "/api/v1/auth/callback",
            "/api/v1/auth/status"
        ]
        if request.path not in public_paths:
            if not session.get("authenticated"):
                return jsonify({
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Acceso denegado: Se requiere autenticación."
                    }
                }), 401

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

    # Configuración de cookies de sesión (Seguridad RNF-01)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = not app.config["DEBUG"]
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

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
    from app.api.categories import categories_bp
    from app.api.channels import channels_bp
    from app.api.health import health_bp
    from app.auth.routes import auth_bp

    # Registramos con el prefijo /api/v1 como especifica openapi.yaml
    app.register_blueprint(health_bp, url_prefix="/api/v1")
    app.register_blueprint(categories_bp, url_prefix="/api/v1")
    app.register_blueprint(channels_bp, url_prefix="/api/v1")
    app.register_blueprint(auth_bp, url_prefix="/api/v1")

    # Registrar middlewares/before_request hooks
    app.before_request(csrf_protect)
    app.before_request(check_auth)

    # Ruta base / que sirve el frontend
    @app.route("/")
    def index():
        from flask import render_template
        return render_template("base.html")

    return app
