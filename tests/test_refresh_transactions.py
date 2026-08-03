import json
import sys

from app.db import get_db_connection
from app.repositories.refresh_run_repository import RefreshRunRepository
from app.services.refresh_orchestrator import RefreshOrchestrator
from app.services.subscription_service import SubscriptionService


class FaultySubscriptionService(SubscriptionService):
    def sync_subscriptions(self, db, heartbeat_callback=None):
        # Insert business row
        db.execute(
            "INSERT INTO channels (youtube_channel_id, title, created_at, updated_at) "
            "VALUES ('UC_ERR', 'Error Channel', 'now', 'now')"
        )
        # Raise sensitive exception
        raise Exception(
            "Sensitive: token=SECRET https://external.example/private remote-body-confidential"
        )


def test_corr_ref_03_stage_error_rolls_back_business_db(app):
    """CORR-REF-03 — Si una etapa lanza un error, se hace rollback y se registra en errors_json sin datos sensibles."""
    db_path = app.config["DATABASE_PATH"]
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, "
                "requested_at, counters_json, errors_json) "
                "VALUES (1, 'pending', '[\"subscriptions\"]', NULL, 'now', '{}', '[]')"
            )
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

    # Verify results
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            row = conn.execute("SELECT 1 FROM channels WHERE youtube_channel_id = 'UC_ERR'").fetchone()
            assert row is None, "Business changes of failed stage must be rolled back"

            run = conn.execute("SELECT status, errors_json FROM refresh_runs WHERE id = 1").fetchone()
            assert run["status"] == "failed"

            errors = json.loads(run["errors_json"])
            assert isinstance(errors, list), "errors_json should be a list"
            assert len(errors) == 1, f"Should have exactly 1 error, got {len(errors)}"

            err = errors[0]
            assert isinstance(err, dict), f"Error item must be a dict, got {type(err)}"
            assert "stage" in err, "Error must have 'stage' key"
            assert "code" in err, "Error must have 'code' key"
            assert "message" in err, "Error must have 'message' key"

            assert err["stage"] == "subscriptions"

            # Check sanitization of message
            msg = err["message"]
            assert "SECRET" not in msg, "Sensitive token leaked"
            assert "token=" not in msg, "Token parameter pattern leaked"
            assert "https://external.example" not in msg, "URL leaked"
            assert "remote-body-confidential" not in msg, "Confidential body leaked"
            assert "Traceback" not in msg, "Tracebacks must not be exposed"
        finally:
            conn.close()
