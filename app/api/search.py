from flask import Blueprint, jsonify, request

from app.db import get_db
from app.services.search_service import SearchService

search_bp = Blueprint("search", __name__)


@search_bp.route("/search", methods=["GET"])
def search_youtube():
    """
    Endpoint para búsqueda inteligente en YouTube API orientada a canales suscritos.
    Retorna videos de creadores suscritos y descubrimientos externos limpios.
    """
    query = request.args.get("query", "").strip()
    limit = min(request.args.get("limit", default=25, type=int), 50)

    if not query:
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "El parámetro query es obligatorio y no puede estar vacío."
            }
        }), 400

    db = get_db()
    service = SearchService()
    try:
        results = service.search(db, query, limit=limit)
        return jsonify(results), 200
    except Exception as e:
        return jsonify({
            "error": {
                "code": "SEARCH_ERROR",
                "message": f"Error al ejecutar la búsqueda en YouTube: {e}"
            }
        }), 502
