import pytest
import json
from app.db import get_db_connection
from app.repositories.discovery_repository import DiscoveryRepository
from app.domain.discovery.models import Band, DiscoveryCandidateDomain

def test_discovery_repository_operations(app):
    """Prueba las operaciones básicas de candidatos, lotes y feedback de descubrimiento."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        
        # Insertar categoría para FK
        db.execute("""
            INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
            VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')
        """)
        # Insertar refresh run para FK
        db.execute("""
            INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json)
            VALUES (1, 'running', '[]', 'discovery', 'now', '{}', '{}')
        """)
        db.commit()

        # 1. Crear canal y video candidatos
        channel_data = {"youtube_channel_id": "UC_CAND", "title": "Canal Candidato", "description": "Desc"}
        video_data = {"youtube_video_id": "vid_cand", "title": "Video de Prueba", "published_at": "2026-07-30T10:00:00Z", "duration_seconds": 300, "content_type": "video"}
        
        cid, vid = DiscoveryRepository.upsert_channel_and_video(db, channel_data, video_data)
        assert cid > 0
        assert vid > 0
        
        # 2. Guardar candidato con category_id = 1
        candidate = DiscoveryCandidateDomain(
            video_id=vid,
            youtube_video_id="vid_cand",
            channel_id=cid,
            youtube_channel_id="UC_CAND",
            channel_title="Canal Candidato",
            title="Video de Prueba",
            description="Desc",
            published_at="2026-07-30T10:00:00Z",
            duration_seconds=300,
            content_type="video",
            score=88.5,
            band=Band.RELATED,
            reasons=["Razón de prueba"],
            selection_rank=1,
            category_id=1
        )
        
        # Guardar bajo refresh_run_id=1
        DiscoveryRepository.save_discovery_candidate(db, candidate, refresh_run_id=1)
        
        # 3. Consultar recomendaciones del lote activo
        recs, batches, next_cursor = DiscoveryRepository.get_active_batch_recommendations(db, category_id=1, limit=10)
        assert len(recs) == 1
        assert recs[0]["video"]["youtubeVideoId"] == "vid_cand"
        assert recs[0]["context"]["score"] == 88.5
        assert recs[0]["context"]["reasons"] == ["Razón de prueba"]
        
        db.close()

def test_discovery_feedback_side_effects(app):
    """Prueba los efectos colaterales de las acciones de feedback (bloqueo, ocultamiento, aceptación)."""
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        
        # Insertar categoría para FK
        db.execute("""
            INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
            VALUES (1, 'Cat A', 'cat-a', 1, 'now', 'now')
        """)
        # Insertar refresh run para FK
        db.execute("""
            INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json)
            VALUES (1, 'running', '[]', 'discovery', 'now', '{}', '{}')
        """)
        db.commit()

        # Configurar datos iniciales
        channel_data = {"youtube_channel_id": "UC_FB", "title": "Canal Feedback"}
        video_data = {"youtube_video_id": "vid_fb", "title": "Video Feedback", "published_at": "2026-07-30T10:00:00Z"}
        cid, vid = DiscoveryRepository.upsert_channel_and_video(db, channel_data, video_data)
        
        candidate = DiscoveryCandidateDomain(
            video_id=vid,
            youtube_video_id="vid_fb",
            channel_id=cid,
            youtube_channel_id="UC_FB",
            channel_title="Canal Feedback",
            title="Video Feedback",
            description="",
            published_at="2026-07-30T10:00:00Z",
            duration_seconds=300,
            content_type="video",
            score=75.0,
            band=Band.RELATED,
            reasons=["Razón"]
        )
        # Forzar category_id=1
        candidate.category_id = 1
        DiscoveryRepository.save_discovery_candidate(db, candidate, refresh_run_id=1)
        
        # Verificar que es activo
        recs, _, _ = DiscoveryRepository.get_active_batch_recommendations(db, category_id=1)
        assert len(recs) == 1
        assert recs[0]["video"]["id"] == vid
        
        # A) Ocultar video
        DiscoveryRepository.save_feedback(db, video_id=vid, channel_id=cid, category_id=1, action="hide_video")
        recs_hide, _, _ = DiscoveryRepository.get_active_batch_recommendations(db, category_id=1)
        assert len(recs_hide) == 0  # Ya no debe aparecer
        
        # Revertir ocultación para probar bloqueo
        db.execute("UPDATE discovery_candidates SET status = 'active' WHERE video_id = ?", (vid,))
        db.commit()
        
        # B) Bloquear canal
        DiscoveryRepository.save_feedback(db, video_id=vid, channel_id=cid, category_id=1, action="block_channel")
        # El canal debe estar marcado como is_blocked = 1
        cursor = db.execute("SELECT is_blocked FROM channels WHERE id = ?", (cid,))
        assert cursor.fetchone()["is_blocked"] == 1
        # Ya no debe aparecer en recomendaciones activas
        recs_block, _, _ = DiscoveryRepository.get_active_batch_recommendations(db, category_id=1)
        assert len(recs_block) == 0
        
        # C) Aceptar canal (en un canal no bloqueado)
        channel_data2 = {"youtube_channel_id": "UC_FB2", "title": "Canal Feedback 2"}
        video_data2 = {"youtube_video_id": "vid_fb2", "title": "Video Feedback 2", "published_at": "2026-07-30T10:00:00Z"}
        cid2, vid2 = DiscoveryRepository.upsert_channel_and_video(db, channel_data2, video_data2)
        
        candidate2 = DiscoveryCandidateDomain(
            video_id=vid2,
            youtube_video_id="vid_fb2",
            channel_id=cid2,
            youtube_channel_id="UC_FB2",
            channel_title="Canal Feedback 2",
            title="Video Feedback 2",
            description="",
            published_at="2026-07-30T10:00:00Z",
            duration_seconds=300,
            content_type="video",
            score=75.0,
            band=Band.RELATED,
            reasons=["Razón"]
        )
        candidate2.category_id = 1
        DiscoveryRepository.save_discovery_candidate(db, candidate2, refresh_run_id=1)
        
        DiscoveryRepository.save_feedback(db, video_id=vid2, channel_id=cid2, category_id=1, action="accept_channel")
        # El canal debe estar marcado como is_locally_followed = 1
        cursor = db.execute("SELECT is_locally_followed FROM channels WHERE id = ?", (cid2,))
        assert cursor.fetchone()["is_locally_followed"] == 1
        
        # Debe haberse creado la asociación de categoría
        cursor = db.execute("SELECT count(*) as cant FROM channel_categories WHERE channel_id = ? AND category_id = 1", (cid2,))
        assert cursor.fetchone()["cant"] == 1
        
        db.close()
