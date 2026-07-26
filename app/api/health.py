from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)

@health_bp.route("/health", methods=["GET"])
def health():
    """Endpoint de diagnóstico básico que responde 'ok'."""
    return jsonify({"status": "ok"}), 200
