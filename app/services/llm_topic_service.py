import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMTopicService:
    @staticmethod
    def generate_topics(
        category_name: str,
        category_description: Optional[str] = None,
        seed_channel_titles: Optional[List[str]] = None,
        existing_keywords: Optional[List[str]] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        ollama_url: Optional[str] = None,
        ollama_model: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Genera una lista de diccionarios [{'term': '...', 'rationale': '...'}]
        usando Gemini API u Ollama.
        """
        provider = (provider or os.environ.get("LLM_PROVIDER", "gemini")).lower()

        channels_text = ", ".join(seed_channel_titles[:15]) if seed_channel_titles else "Ninguno"
        keywords_text = ", ".join(existing_keywords[:15]) if existing_keywords else "Ninguna"
        desc_text = category_description or "Sin descripción"

        prompt = f"""Sos un curador de contenido experto. Dado el siguiente perfil de una categoría de interés en YouTube:

- Nombre de la categoría: {category_name}
- Descripción: {desc_text}
- Canales que el usuario sigue en esta categoría: {channels_text}
- Palabras clave existentes: {keywords_text}

Tu objetivo es proponer entre 3 y 5 temas de exploración adyacentes o conceptos relacionados que NO estén ya incluidos en las palabras clave ni sean idénticos a los nombres de canales. Deben ser términos breves (1 a 3 palabras) con alto interés potencial para el usuario.

IMPORTANTE: Responde ÚNICAMENTE con una matriz JSON válida sin formato Markdown envolvente ni bloques ```json.
Cada elemento debe tener la forma:
[
  {{
    "term": "Nombre del Tema",
    "rationale": "Breve explicación en español de por qué es relevante (máximo 15 palabras)."
  }}
]"""

        if provider == "ollama":
            return LLMTopicService._call_ollama(prompt, ollama_url, ollama_model)
        else:
            return LLMTopicService._call_gemini(prompt, api_key)

    @staticmethod
    def _call_gemini(prompt: str, api_key: Optional[str] = None) -> List[Dict[str, str]]:
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key or key == "your-gemini-api-key-here":
            raise ValueError("GEMINI_API_KEY no está configurada en las variables de entorno.")

        # Usar endpoint REST oficial v1beta de Gemini
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.4,
                "responseMimeType": "application/json"
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
                return LLMTopicService._parse_json_response(text)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else ""
            logger.error(f"Error de API de Gemini (HTTP {e.code}): {err_body}")
            if e.code == 404:
                return LLMTopicService._call_gemini_fallback(prompt, key)
            raise RuntimeError(f"Error HTTP {e.code} al consultar Gemini API.")
        except Exception as e:
            logger.error(f"Error al llamar a Gemini: {e}")
            raise RuntimeError(f"Error al consultar Gemini API: {e}")

    @staticmethod
    def _call_gemini_fallback(prompt: str, key: str) -> List[Dict[str, str]]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"}
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
            return LLMTopicService._parse_json_response(text)

    @staticmethod
    def _call_ollama(prompt: str, ollama_url: Optional[str] = None, ollama_model: Optional[str] = None) -> List[Dict[str, str]]:
        base_url = ollama_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model = ollama_model or os.environ.get("OLLAMA_MODEL", "llama3.2")
        url = f"{base_url.rstrip('/')}/api/generate"

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                text = resp_data.get("response", "")
                return LLMTopicService._parse_json_response(text)
        except Exception as e:
            logger.error(f"Error al llamar a Ollama local: {e}")
            raise RuntimeError(f"Error al conectar con Ollama ({base_url}): {e}")

    @staticmethod
    def _parse_json_response(text: str) -> List[Dict[str, str]]:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        data = json.loads(cleaned)
        if isinstance(data, dict):
            for k in ["topics", "items", "data", "results"]:
                if k in data and isinstance(data[k], list):
                    data = data[k]
                    break

        if not isinstance(data, list):
            raise ValueError("Respuesta inválida del LLM: no retornó una lista JSON.")

        results = []
        for item in data:
            if isinstance(item, dict) and "term" in item:
                term = str(item["term"]).strip()
                rationale = str(item.get("rationale", "Sugerido por IA.")).strip()
                if term:
                    results.append({"term": term, "rationale": rationale})

        return results
