import pytest
import json
from unittest.mock import MagicMock
from app.db import get_db_connection
from app.repositories.refresh_run_repository import RefreshRunRepository
from app.services.refresh_orchestrator import RefreshOrchestrator
from tests.fakes.youtube_gateway import FakeYouTubeGateway

def test_refresh_orchestrator_claim_and_run(app):
    """Prueba que un worker puede reclamar un refresh run y ejecutar sus etapas."""
    fake_gateway = FakeYouTubeGateway()
    
    with app.app_context():
        db = get_db_connection(app.config["DATABASE_PATH"])
        
        # 1. Crear refresh run pendiente
        run_id = RefreshRunRepository.create(db, ["subscriptions"])
        assert run_id is not None
        
        # 2. Reclamar por un worker
        job = RefreshRunRepository.claim_job(db, worker_id="worker_1", lease_duration_seconds=10)
        assert job is not None
        assert job["status"] == "running"
        assert job["worker_id"] == "worker_1"
        
        # Intentar reclamar por otro worker (no debe poder)
        job2 = RefreshRunRepository.claim_job(db, worker_id="worker_2")
        assert job2 is None
        
        # 3. Configurar credenciales ficticias de YouTube
        from app.auth.encryption import encrypt_token
        enc_access = encrypt_token("mock-access")
        enc_refresh = encrypt_token("mock-refresh")
        db.execute("""
            INSERT INTO credentials (id, access_token, refresh_token, expires_at, updated_at)
            VALUES (1, ?, ?, '2030-01-01T00:00:00Z', 'now')
        """, (enc_access, enc_refresh))
        db.commit()
        
        # 4. Correr orquestador
        orchestrator = RefreshOrchestrator(gateway=fake_gateway)
        orchestrator.run_refresh(db, run_id=run_id, worker_id="worker_1")
        
        # 5. Verificar estado final de éxito
        final_job = RefreshRunRepository.get_by_id(db, run_id)
        assert final_job["status"] == "succeeded"
        
        db.close()
