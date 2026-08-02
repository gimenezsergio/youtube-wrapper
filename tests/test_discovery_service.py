from app.auth.encryption import encrypt_token
from app.db import get_db_connection
from app.repositories.discovery_repository import DiscoveryRepository
from app.services.discovery_service import DiscoveryService
from tests.fakes.youtube_gateway import FakeYouTubeGateway


def test_discovery_service_e2e_flow(app):
    """Prueba el flujo e2e de DiscoveryService con un gateway fake determinista."""
    # Configurar fake gateway
    fake_gateway = FakeYouTubeGateway()
    # Inyectar resultados de búsqueda simulados
    fake_gateway.search_responses["default"] = [
        {
            "youtube_video_id": "vid_photo_1",
            "title": "Aprender fotografía de retratos",
            "description": "Curso completo",
            "published_at": "2026-07-30T10:00:00Z",
            "thumbnail_url": "thumb_1",
            "channel_title": "Canal Foto 1",
            "youtube_channel_id": "UC_FOTO_1"
        },
        {
            "youtube_video_id": "vid_photo_2",
            "title": "Fotografía de paisajes avanzado",
            "description": "Paisajes",
            "published_at": "2026-07-30T09:00:00Z",
            "thumbnail_url": "thumb_2",
            "channel_title": "Canal Foto 2",
            "youtube_channel_id": "UC_FOTO_2"
        }
    ]

    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])

        # 1. Configurar credenciales ficticias de YouTube
        enc_access = encrypt_token("mock-access")
        enc_refresh = encrypt_token("mock-refresh")
        db.execute("""
            INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at)
            VALUES (1, ?, ?, '2030-01-01T00:00:00Z', 'now')
        """, (enc_access, enc_refresh))
        # Configurar categoría y palabras clave
        db.execute("""
            INSERT INTO categories (id, name, normalized_name, position, created_at, updated_at)
            VALUES (1, 'Fotografía', 'fotografia', 1, 'now', 'now')
        """)
        db.execute("""
            INSERT INTO category_keywords (category_id, term, polarity, weight)
            VALUES (1, 'fotografia', 'positive', 5.0)
        """)

        # Insertar refresh run para FK
        db.execute("""
            INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json)
            VALUES (1, 'running', '["discovery"]', 'discovery', 'now', '{}', '{}')
        """)
        db.commit()

        # 2. Instanciar servicio de descubrimiento e invocarlo
        disc_service = DiscoveryService(gateway=fake_gateway)
        stats = disc_service.run_discovery(db, run_id=1)

        # 3. Validaciones de resultados
        assert stats["searches_executed"] > 0
        assert stats["categories"][1]["selected"] == 2 # Se encontraron y seleccionaron 2 videos

        # Verificar candidatos en base de datos
        recs, batches, _ = DiscoveryRepository.get_active_batch_recommendations(db, category_id=1)
        assert len(recs) == 2
        assert recs[0]["video"]["youtubeVideoId"] == "vid_photo_1"
        assert recs[1]["video"]["youtubeVideoId"] == "vid_photo_2"

        db.close()
