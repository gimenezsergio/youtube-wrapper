from flask import Blueprint, jsonify, request

from app.db import get_db
from app.repositories.category_repository import CategoryRepository

categories_bp = Blueprint("categories", __name__)

def _validate_keywords(keywords, errors):
    """Auxiliar para validar la lista de palabras clave."""
    if not isinstance(keywords, list):
        errors["keywords"] = "Las palabras clave deben proveerse como una lista."
        return

    for idx, kw in enumerate(keywords):
        if not isinstance(kw, dict):
            errors[f"keywords.{idx}"] = "Cada palabra clave debe ser un objeto."
            continue

        term = kw.get("term")
        if not term or not isinstance(term, str) or not term.strip():
            errors[f"keywords.{idx}.term"] = "El término es obligatorio y no puede estar vacío."
        elif len(term) > 120:
            errors[f"keywords.{idx}.term"] = "El término no puede exceder los 120 caracteres."

        polarity = kw.get("polarity")
        if polarity not in ["positive", "negative"]:
            errors[f"keywords.{idx}.polarity"] = "La polaridad debe ser 'positive' o 'negative'."

        weight = kw.get("weight")
        if weight is not None:
            try:
                w_val = float(weight)
                if w_val < 0.0 or w_val > 10.0:
                    errors[f"keywords.{idx}.weight"] = "El peso debe estar entre 0.0 y 10.0."
            except (ValueError, TypeError):
                errors[f"keywords.{idx}.weight"] = "El peso debe ser un valor numérico."

def validate_category_input(data):
    """Valida los campos obligatorios y límites de longitud de la categoría."""
    errors = {}

    # Validar nombre
    name = data.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        errors["name"] = "El nombre de la categoría es obligatorio y debe ser una cadena no vacía."
    elif len(name) > 80:
        errors["name"] = "El nombre no puede exceder los 80 caracteres."

    # Validar descripción
    description = data.get("description")
    if description is not None:
        if not isinstance(description, str):
            errors["description"] = "La descripción debe ser una cadena de texto."
        elif len(description) > 500:
            errors["description"] = "La descripción no puede exceder los 500 caracteres."

    # Validar palabras clave (keywords)
    keywords = data.get("keywords")
    if keywords is not None:
        _validate_keywords(keywords, errors)

    return errors

@categories_bp.route("/categories", methods=["GET"])
def list_categories():
    """Listar todas las categorías ordenadas por posición."""
    db = get_db()
    items = CategoryRepository.list_all(db)
    return jsonify({"items": items}), 200

@categories_bp.route("/categories", methods=["POST"])
def create_category():
    """Crear una nueva categoría."""
    data = request.get_json(silent=True) or {}
    errors = validate_category_input(data)
    if errors:
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Error al validar la entrada de la categoría.",
                "details": errors
            }
        }), 422

    db = get_db()
    try:
        category = CategoryRepository.create(
            db,
            name=data["name"],
            description=data.get("description"),
            keywords=data.get("keywords")
        )
        return jsonify(category), 201
    except ValueError as e:
        return jsonify({
            "error": {
                "code": "DUPLICATE_CATEGORY",
                "message": str(e)
            }
        }), 409

@categories_bp.route("/categories/<int:category_id>", methods=["GET"])
def get_category(category_id):
    """Obtener los detalles de una categoría."""
    db = get_db()
    category = CategoryRepository.get_by_id(db, category_id)
    if not category:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": "Categoría no encontrada."
            }
        }), 404
    return jsonify(category), 200

@categories_bp.route("/categories/<int:category_id>", methods=["PUT"])
def update_category(category_id):
    """Actualizar una categoría existente."""
    data = request.get_json(silent=True) or {}
    errors = validate_category_input(data)
    if errors:
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Error al validar la entrada de la categoría.",
                "details": errors
            }
        }), 422

    db = get_db()
    try:
        category = CategoryRepository.update(
            db,
            category_id=category_id,
            name=data["name"],
            description=data.get("description"),
            keywords=data.get("keywords")
        )
        if not category:
            return jsonify({
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Categoría no encontrada."
                }
            }), 404
        return jsonify(category), 200
    except ValueError as e:
        return jsonify({
            "error": {
                "code": "DUPLICATE_CATEGORY",
                "message": str(e)
            }
        }), 409

@categories_bp.route("/categories/<int:category_id>", methods=["DELETE"])
def delete_category(category_id):
    """Eliminar una categoría y limpiar dependencias en cascada."""
    db = get_db()
    success = CategoryRepository.delete(db, category_id)
    if not success:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": "Categoría no encontrada."
            }
        }), 404
    return "", 204

@categories_bp.route("/categories/reorder", methods=["PUT"])
def reorder_categories():
    """Reordenar categorías de forma atómica."""
    data = request.get_json(silent=True) or {}
    category_ids = data.get("categoryIds")

    if not category_ids or not isinstance(category_ids, list):
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Es necesario proveer una lista de IDs de categorías en 'categoryIds'."
            }
        }), 422

    db = get_db()
    try:
        CategoryRepository.reorder(db, category_ids)
        return "", 204
    except Exception as e:
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": f"Error al reordenar las categorías: {e}"
            }
        }), 500
