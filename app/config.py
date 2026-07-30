import os
from pathlib import Path

from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env si existe
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

class Config:
    """Configuración base común."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "default-dev-secret-key-change-in-production")

    # Base de datos
    DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "youtube_curator.db"))

    # Default de fallback para desarrollo/test
    TOKEN_ENCRYPTION_KEY = os.environ.get(
        "TOKEN_ENCRYPTION_KEY", "K3V3WVhFdmh3Skl2eFhDWTFzTkpxUWx6T0RJM05EUTU="
    )

    # OAuth Propietario
    OWNER_GOOGLE_EMAIL = os.environ.get("OWNER_GOOGLE_EMAIL")

    # Google OAuth 2.0 Client Credentials
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")

    # Presupuestos y Umbrales
    CLASSIFY_AUTO_THRESHOLD = float(os.environ.get("CLASSIFY_AUTO_THRESHOLD", 0.85))
    CLASSIFY_SUGGEST_THRESHOLD = float(os.environ.get("CLASSIFY_SUGGEST_THRESHOLD", 0.55))

    DISCOVERY_MAX_SEARCHES_PER_REFRESH = int(os.environ.get("DISCOVERY_MAX_SEARCHES_PER_REFRESH", 50))
    DISCOVERY_MAX_SEARCHES_PER_CATEGORY = int(os.environ.get("DISCOVERY_MAX_SEARCHES_PER_CATEGORY", 5))

    TESTING = False
    DEBUG = False


class DevelopmentConfig(Config):
    """Configuración para desarrollo."""
    DEBUG = True
    DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "youtube_curator_dev.db"))


class TestingConfig(Config):
    """Configuración para pruebas."""
    TESTING = True
    DEBUG = True
    DATABASE_PATH = ":memory:"
    # Clave de cifrado de prueba
    TOKEN_ENCRYPTION_KEY = "K3V3WVhFdmh3Skl2eFhDWTFzTkpxUWx6T0RJM05EUTU="
    OWNER_GOOGLE_EMAIL = "test_owner@gmail.com"
    GOOGLE_CLIENT_ID = "test-client-id"
    GOOGLE_CLIENT_SECRET = "test-client-secret"
    GOOGLE_REDIRECT_URI = "http://localhost:5000/api/v1/auth/callback"


class ProductionConfig(Config):
    """Configuración para producción."""
    # En producción los secretos DEBEN venir del entorno, no usamos defaults inseguros
    def __init__(self):
        super().__init__()
        # Validar secretos obligatorios en producción
        required = [
            "SECRET_KEY",
            "OWNER_GOOGLE_EMAIL",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_REDIRECT_URI",
        ]
        missing = [r for r in required if not os.environ.get(r)]
        if missing:
            raise ValueError(f"Faltan variables de entorno obligatorias para Producción: {', '.join(missing)}")

        # Validar la clave de cifrado
        tok_key = os.environ.get("TOKEN_ENCRYPTION_KEY")
        if not tok_key or tok_key == "K3V3WVhFdmh3Skl2eFhDWTFzTkpxUWx6T0RJM05EUTU=":
            raise ValueError("Debe configurar una TOKEN_ENCRYPTION_KEY segura y única en producción")


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}

def get_config(config_name=None):
    """Obtiene la configuración correspondiente al nombre o variable de entorno."""
    if not config_name:
        config_name = os.environ.get("FLASK_ENV", "development")
    return config_by_name.get(config_name, DevelopmentConfig)
