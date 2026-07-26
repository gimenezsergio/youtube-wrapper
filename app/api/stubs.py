from flask import Blueprint, jsonify

stubs_bp = Blueprint("stubs", __name__)

@stubs_bp.route("/auth/status", methods=["GET"])
def auth_status():
    """Stub del estado de autenticación."""
    # Retorna que el usuario no está autenticado por defecto en Fase 0
    return jsonify({
        "authenticated": False,
        "email": None,
        "csrfToken": "mock-csrf-token-fase-0"
    }), 200

@stubs_bp.route("/categories", methods=["GET"])
def list_categories():
    """Stub de listado de categorías."""
    # Retorna algunas categorías de ejemplo en Fase 0
    return jsonify({
        "items": [
            {
                "id": 1,
                "name": "Tecnología",
                "description": "Canales sobre programación, hardware y software libre",
                "keywords": [],
                "position": 1,
                "channelCount": 0
            },
            {
                "id": 2,
                "name": "Fotografía",
                "description": "Técnicas de cámara, edición y reviews de equipo",
                "keywords": [],
                "position": 2,
                "channelCount": 0
            }
        ]
    }), 200
