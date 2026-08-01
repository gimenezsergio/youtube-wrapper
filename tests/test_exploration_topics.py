import pytest
from app.db import get_db_connection
from app.repositories.exploration_topic_repository import ExplorationTopicRepository

def test_exploration_topics_crud(app):
    """Prueba las operaciones del repositorio de temas de exploración."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        
        # Insertar categoría para FK
        db.execute("""
            INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
            VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')
        """)
        db.commit()

        # 1. Crear tema manual aprobado
        topic_id = ExplorationTopicRepository.create_manual_approved(db, category_id=1, term="Dirección de Arte", weight=1.2)
        assert topic_id is not None
        
        # 2. Consultar por término normalizado
        topic = ExplorationTopicRepository.get_by_category_and_term(db, category_id=1, term="dirección de arte")
        assert topic is not None
        assert topic["normalized_term"] == "direccion de arte"
        assert topic["weight"] == 1.2
        assert topic["status"] == "approved"
        assert topic["source"] == "manual"
        
        # 3. Insertar propuesta automática pendiente
        auto_id = ExplorationTopicRepository.insert_automatic_pending(db, category_id=1, term="Escenografía", weight=1.0, rationale="Tema visual")
        assert auto_id is not None
        
        # 4. Intentar duplicar propuesta automática (debe retornar None o no hacer nada)
        dup_id = ExplorationTopicRepository.insert_automatic_pending(db, category_id=1, term="escenografía", weight=1.0)
        assert dup_id is None
        
        # 5. Listar temas por categoría
        topics = ExplorationTopicRepository.list_by_category(db, category_id=1)
        assert len(topics) == 2
        
        # 6. Actualizar estado a aprobado o rechazado
        ExplorationTopicRepository.update_status(db, auto_id, status="rejected", rationale="No interesa")
        updated_topic = ExplorationTopicRepository.get_by_category_and_term(db, category_id=1, term="escenografía")
        assert updated_topic["status"] == "rejected"
        assert updated_topic["rationale"] == "No interesa"
        
        db.close()
