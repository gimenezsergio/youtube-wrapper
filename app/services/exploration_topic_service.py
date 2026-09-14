import re
from typing import Any, Dict, List, Optional

from app.domain.discovery.normalization import normalize_term
from app.repositories.exploration_topic_repository import ExplorationTopicRepository

SPANISH_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "y", "o", "u", "e", "en", "para", "por",
    "con", "sin", "sobre", "que", "como", "tutorial", "video", "canal", "oficial", "pero", "este", "esta", "sino"
}

class ExplorationTopicService:
    @staticmethod
    def list_topics(db, category_id: int) -> List[Dict[str, Any]]:
        """Retorna todos los temas de exploración para la categoría."""
        return ExplorationTopicRepository.list_by_category(db, category_id)

    @staticmethod
    def create_manual_topic(db, category_id: int, term: str, weight: float = 1.0) -> int:
        """Crea un tema adyacente manual aprobado."""
        if not term or not term.strip():
            raise ValueError("El término del tema no puede estar vacío.")
        return ExplorationTopicRepository.create_manual_approved(db, category_id, term.strip(), weight)

    @staticmethod
    def update_topic_status(db, topic_id: int, status: str, rationale: Optional[str] = None) -> bool:
        """Cambia el estado de un tema adyacente (approved, pending, rejected)."""
        return ExplorationTopicRepository.update_status(db, topic_id, status, rationale)

    @staticmethod
    def generate_automatic_proposals(db, category_id: int) -> int:
        """
        Genera propuestas automáticas (status='pending') analizando la frecuencia
        de palabras en títulos de canales semilla y videos recientes de la categoría.
        """
        # 1. Obtener títulos de canales semilla
        cursor = db.execute("""
            SELECT c.title, c.description
            FROM channels c
            JOIN channel_categories cc ON c.id = cc.channel_id
            WHERE cc.category_id = ?
        """, (category_id,))
        seed_texts = []
        for row in cursor.fetchall():
            if row["title"]:
                seed_texts.append(row["title"])
            if row["description"]:
                seed_texts.append(row["description"])

        # 2. Obtener títulos de videos recientes
        cursor = db.execute("""
            SELECT v.title
            FROM videos v
            JOIN channel_categories cc ON v.channel_id = cc.channel_id
            WHERE cc.category_id = ?
            ORDER BY v.published_at DESC
            LIMIT 50
        """, (category_id,))
        for row in cursor.fetchall():
            if row["title"]:
                seed_texts.append(row["title"])

        # 3. Obtener exclusiones (palabras clave existentes y temas existentes)
        cursor = db.execute("SELECT term FROM category_keywords WHERE category_id = ?", (category_id,))
        excl_terms = {normalize_term(row["term"]) for row in cursor.fetchall()}

        existing_topics = ExplorationTopicRepository.list_by_category(db, category_id)
        for t in existing_topics:
            excl_terms.add(t["normalized_term"])

        # 4. Contar frecuencias de palabras válidas
        word_freqs = {}
        for text in seed_texts:
            normalized = normalize_term(text)
            words = re.findall(r'\w+', normalized)
            for w in words:
                if len(w) > 3 and w not in SPANISH_STOPWORDS and w not in excl_terms:
                    word_freqs[w] = word_freqs.get(w, 0) + 1

        # 5. Tomar las 3 palabras más frecuentes
        sorted_words = sorted(word_freqs.items(), key=lambda x: x[1], reverse=True)
        top_words = sorted_words[:3]

        inserted_count = 0
        for word, freq in top_words:
            # Proponer
            res = ExplorationTopicRepository.insert_automatic_pending(
                db,
                category_id=category_id,
                term=word.capitalize(),
                weight=1.0,
                rationale=f"Propuesto automáticamente por aparecer {freq} veces en títulos y canales de la categoría."
            )
            if res is not None:
                inserted_count += 1

        return inserted_count

    @staticmethod
    def generate_llm_proposals(db, category_id: int, provider: Optional[str] = None, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Genera propuestas de temas adyacentes utilizando un LLM (Gemini u Ollama),
        recolectando el contexto de la categoría y persistiendo las propuestas en 'pending'.
        """
        from app.services.llm_topic_service import LLMTopicService

        cat_row = db.execute("SELECT name, description FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat_row:
            raise ValueError(f"Categoría {category_id} no encontrada.")

        cat_name = cat_row["name"]
        cat_desc = cat_row["description"]

        channels_rows = db.execute("""
            SELECT c.title
            FROM channels c
            JOIN channel_categories cc ON c.id = cc.channel_id
            WHERE cc.category_id = ?
        """, (category_id,)).fetchall()
        seed_channel_titles = [r["title"] for r in channels_rows if r["title"]]

        kw_rows = db.execute("SELECT term FROM category_keywords WHERE category_id = ?", (category_id,)).fetchall()
        existing_keywords = [r["term"] for r in kw_rows if r["term"]]

        topics = LLMTopicService.generate_topics(
            category_name=cat_name,
            category_description=cat_desc,
            seed_channel_titles=seed_channel_titles,
            existing_keywords=existing_keywords,
            provider=provider,
            api_key=api_key
        )

        inserted_items = []
        for t in topics:
            term = t["term"]
            rationale = t.get("rationale", "Propuesto por IA.")
            topic_id = ExplorationTopicRepository.insert_automatic_pending(
                db,
                category_id=category_id,
                term=term,
                weight=1.0,
                rationale=f"[IA] {rationale}"
            )
            if topic_id is not None:
                inserted_items.append({
                    "id": topic_id,
                    "term": term,
                    "rationale": f"[IA] {rationale}",
                    "status": "pending"
                })

        return inserted_items
