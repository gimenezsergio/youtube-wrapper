from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.domain.discovery.normalization import normalize_term

class ExplorationTopicRepository:
    @staticmethod
    def list_by_category(db, category_id: int) -> List[Dict[str, Any]]:
        """Lista todos los temas de exploración de una categoría."""
        cursor = db.execute("""
            SELECT id, category_id, term, normalized_term, weight, source, status, rationale, created_at, updated_at
            FROM category_exploration_topics
            WHERE category_id = ?
            ORDER BY created_at DESC
        """, (category_id,))
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_category_and_term(db, category_id: int, term: str) -> Optional[Dict[str, Any]]:
        """Obtiene un tema por categoría y término normalizado."""
        norm = normalize_term(term)
        cursor = db.execute("""
            SELECT id, category_id, term, normalized_term, weight, source, status, rationale, created_at, updated_at
            FROM category_exploration_topics
            WHERE category_id = ? AND normalized_term = ?
        """, (category_id, norm))
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def create_manual_approved(db, category_id: int, term: str, weight: float = 1.0) -> int:
        """Crea un tema de exploración manual y lo aprueba de forma predeterminada."""
        now = datetime.now(timezone.utc).isoformat()
        norm = normalize_term(term)
        
        # Verificar si ya existe
        existing = ExplorationTopicRepository.get_by_category_and_term(db, category_id, term)
        if existing:
            # Si existe, actualizamos a aprobado y manual
            db.execute("""
                UPDATE category_exploration_topics
                SET status = 'approved', source = 'manual', weight = ?, updated_at = ?
                WHERE id = ?
            """, (weight, now, existing["id"]))
            return existing["id"]

        cursor = db.execute("""
            INSERT INTO category_exploration_topics (
                category_id, term, normalized_term, weight, source, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'manual', 'approved', ?, ?)
        """, (category_id, term, norm, weight, now, now))
        return cursor.lastrowid

    @staticmethod
    def insert_automatic_pending(db, category_id: int, term: str, weight: float = 1.0, rationale: Optional[str] = None) -> Optional[int]:
        """Propone un tema automático como pending si no existe previamente."""
        now = datetime.now(timezone.utc).isoformat()
        norm = normalize_term(term)

        # Si ya existe (aprobado, pendiente o rechazado), no hacemos nada para evitar duplicar
        existing = ExplorationTopicRepository.get_by_category_and_term(db, category_id, term)
        if existing:
            return None

        cursor = db.execute("""
            INSERT INTO category_exploration_topics (
                category_id, term, normalized_term, weight, source, status, rationale, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'automatic', 'pending', ?, ?, ?)
        """, (category_id, term, norm, weight, rationale, now, now))
        return cursor.lastrowid

    @staticmethod
    def update_status(db, topic_id: int, status: str, rationale: Optional[str] = None) -> bool:
        """Actualiza el estado de un tema de exploración (approved, pending, rejected)."""
        if status not in ('approved', 'pending', 'rejected'):
            raise ValueError(f"Estado de tema inválido: {status}")
        
        now = datetime.now(timezone.utc).isoformat()
        db.execute("""
            UPDATE category_exploration_topics
            SET status = ?, rationale = COALESCE(?, rationale), updated_at = ?
            WHERE id = ?
        """, (status, rationale, now, topic_id))
        return True
