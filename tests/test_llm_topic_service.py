from unittest.mock import MagicMock, patch

import pytest

from app.db import get_db_connection
from app.services.exploration_topic_service import ExplorationTopicService
from app.services.llm_topic_service import LLMTopicService


@pytest.fixture
def auth_client(client):
    """Cliente de pruebas con sesión de propietario iniciada."""
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["email"] = "test_owner@gmail.com"
        sess["csrf_token"] = "mock-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "mock-csrf-token"
    return client


def test_parse_json_response_valid():
    raw_json = """[
        {"term": "WebAssembly", "rationale": "Relevante para rendimiento web."},
        {"term": "Rust Lang", "rationale": "Sugerido por canales de programación."}
    ]"""
    result = LLMTopicService._parse_json_response(raw_json)
    assert len(result) == 2
    assert result[0]["term"] == "WebAssembly"
    assert result[1]["term"] == "Rust Lang"


def test_parse_json_response_markdown_block():
    raw_json = """```json
    [
        {"term": "Docker", "rationale": "Contenedores."}
    ]
    ```"""
    result = LLMTopicService._parse_json_response(raw_json)
    assert len(result) == 1
    assert result[0]["term"] == "Docker"


def test_parse_json_response_wrapped_dict():
    raw_json = """{
        "topics": [
            {"term": "GraphQL", "rationale": "API moderna."}
        ]
    }"""
    result = LLMTopicService._parse_json_response(raw_json)
    assert len(result) == 1
    assert result[0]["term"] == "GraphQL"


def test_gemini_missing_api_key():
    with pytest.raises(ValueError, match="GEMINI_API_KEY no está configurada"):
        LLMTopicService._call_gemini("prompt test", api_key="")


@patch("urllib.request.urlopen")
def test_generate_llm_proposals_e2e(mock_urlopen, app):
    # Mockear respuesta de Gemini API
    mock_response = MagicMock()
    mock_response.read.return_value = (
        b'{"candidates": [{"content": {"parts": [{"text": "[{\\"term\\": \\"Kubernetes\\", \\"rationale\\": \\"Orquestacion\\"}]"}]}}]}'
    )
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        try:
            # Insertar categoría de prueba usando CategoryRepository
            from app.repositories.category_repository import CategoryRepository
            cat = CategoryRepository.create(db, name="DevOps", description="Infraestructura")
            cat_id = cat["id"]

            items = ExplorationTopicService.generate_llm_proposals(db, cat_id, provider="gemini", api_key="test-key")
            assert len(items) == 1
            assert items[0]["term"] == "Kubernetes"
            assert items[0]["status"] == "pending"
            assert "[IA]" in items[0]["rationale"]
        finally:
            db.close()


def test_generate_llm_topics_api_endpoint(auth_client, app):
    with patch("app.services.llm_topic_service.LLMTopicService.generate_topics") as mock_gen:
        mock_gen.return_value = [
            {"term": "OpenAI API", "rationale": "Integración con modelos de IA."}
        ]

        with app.app_context():
            db = get_db_connection(app.config["DATABASE_PATH"])
            try:
                from app.repositories.category_repository import CategoryRepository
                cat = CategoryRepository.create(db, name="Inteligencia Artificial")
                cat_id = cat["id"]
            finally:
                db.close()

        resp = auth_client.post(f"/api/v1/categories/{cat_id}/exploration-topics/generate-llm", json={})
        assert resp.status_code == 201
        data = resp.get_json()
        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["term"] == "OpenAI API"
