import json
import pytest
from app.db import get_db_connection
from app.services.refresh_orchestrator import RefreshOrchestrator
from app.services.subscription_service import SubscriptionService
from app.repositories.refresh_run_repository import RefreshRunRepository

class FaultySubscriptionService(SubscriptionService):
    def sync_subscriptions(self, db, heartbeat_callback=None):
        # Insert a row and then raise Exception (simulating stage failure)
        db.execute("INSERT INTO channels (youtube_channel_id, title, created_at, updated_at) VALUES ('UC_ERR', 'Error Channel', 'now', 'now')")
        raise Exception("Google API Error")

def test_corr_ref_03_stage_error_rolls_back_business_db(app):
    """CORR-REF-03 — Si una etapa lanza un error, se hace rollback de los cambios de negocio de esa etapa y se registra en errors_json sin tracebacks."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            # Create pending run with subscriptions stage
            conn.execute("INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json) VALUES (1, 'pending', '[\"subscriptions\"]', NULL, 'now', '{}', '[]')")
            conn.commit()
        finally:
            conn.close()

        # Claim job first
        conn = get_db_connection(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            RefreshRunRepository.claim_job(conn, "worker-1", 30)
            conn.commit()
        finally:
            conn.close()

        # Setup orchestrator with faulty service
        orchestrator = RefreshOrchestrator()
        # Mock SubscriptionService within run_refresh context
        import sys
        orchestrator_module = sys.modules["app.services.refresh_orchestrator"]
        orig_sub_service = orchestrator_module.SubscriptionService
        orchestrator_module.SubscriptionService = FaultySubscriptionService

        conn = get_db_connection(db_path)
        try:
            orchestrator.run_refresh(conn, run_id=1, worker_id="worker-1")
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
            orchestrator_module.SubscriptionService = orig_sub_service

    # Verify that:
    # 1. The inserted row ('UC_ERR') does not exist (rolled back)
    # 2. The refresh run status is 'failed'
    # 3. The error message is sanitized (no Traceback)
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            row = conn.execute("SELECT 1 FROM channels WHERE youtube_channel_id = 'UC_ERR'").fetchone()
            assert row is None, "Business changes of failed stage must be rolled back"

            run = conn.execute("SELECT status, errors_json FROM refresh_runs WHERE id = 1").fetchone()
            assert run["status"] == "failed"
            
            errors = json.loads(run["errors_json"])
            assert len(errors) == 1
            err = errors[0]
            assert err["stage"] == "subscriptions"
            assert "Google API Error" in err["message"]
            assert "Traceback" not in err["message"], "Tracebacks must not be exposed"
        finally:
            conn.close()
