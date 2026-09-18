from app.repositories.refresh_run_repository import RefreshRunRepository
from app.services.refresh_scheduler import DEFAULT_REFRESH_STAGES, enqueue_refresh


def test_enqueue_refresh_creates_a_complete_pending_run(app):
    run_id = enqueue_refresh(app.config["DATABASE_PATH"])

    assert run_id is not None
    with app.app_context():
        from app.db import get_db_connection

        db = get_db_connection(app.config["DATABASE_PATH"])
        run = RefreshRunRepository.get_by_id(db, run_id)
        db.close()

    assert run["status"] == "pending"
    assert all(stage in run["requested_stages_json"] for stage in DEFAULT_REFRESH_STAGES)


def test_enqueue_refresh_does_not_duplicate_an_active_run(app):
    first_run_id = enqueue_refresh(app.config["DATABASE_PATH"])
    second_run_id = enqueue_refresh(app.config["DATABASE_PATH"])

    assert first_run_id is not None
    assert second_run_id is None
