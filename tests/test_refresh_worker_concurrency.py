import pytest
from app.db import get_db_connection
from app.repositories.refresh_run_repository import RefreshRunRepository

def test_corr_ref_04_concurrency_double_claim(app):
    """CORR-REF-04 — Dos workers intentan reclamar el mismo trabajo; exactamente uno lo obtiene."""
    db_path = app.config["DATABASE_PATH"]
    conn = get_db_connection(db_path)
    try:
        # Create a pending job
        conn.execute("INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, requested_at, counters_json, errors_json) VALUES (1, 'pending', '[\"discovery\"]', NULL, 'now', '{}', '[]')")
        conn.commit()
    finally:
        conn.close()

    # Open two separate database connections (simulating two workers)
    c1 = get_db_connection(db_path)
    c2 = get_db_connection(db_path)
    try:
        # Worker 1 begins transaction and claims job 1
        c1.execute("BEGIN IMMEDIATE")
        job1 = RefreshRunRepository.claim_job(c1, "worker-1", lease_duration_seconds=30)
        
        # Worker 2 attempts to claim job 1, but c1 holds the lock / job is claimed
        # c2.execute will fail or return None when c1 commits and c2 runs
        c1.commit()

        # Now worker 2 attempts (since job1 is committed, it should find no pending job)
        c2.execute("BEGIN IMMEDIATE")
        job2 = RefreshRunRepository.claim_job(c2, "worker-2", lease_duration_seconds=30)
        c2.commit()

        assert job1 is not None, "Worker 1 should successfully claim the job"
        assert job1["id"] == 1
        assert job1["worker_id"] == "worker-1"

        assert job2 is None, "Worker 2 should get None because the job is already claimed and not expired"
    finally:
        c1.close()
        c2.close()
