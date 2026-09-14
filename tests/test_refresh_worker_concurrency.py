import threading

from app.db import get_db_connection
from app.repositories.refresh_run_repository import RefreshRunRepository


def test_corr_ref_04_concurrency_double_claim(app):
    """CORR-REF-04 — Dos workers intentan reclamar el mismo trabajo de forma concurrente en hilos separados."""
    db_path = app.config["DATABASE_PATH"]

    # 1. Setup: Crear un único trabajo pendiente
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO refresh_runs (id, status, requested_stages_json, current_stage, "
                "requested_at, counters_json, errors_json) "
                "VALUES (1, 'pending', '[\"discovery\"]', NULL, 'now', '{}', '[]')"
            )
            conn.commit()
        finally:
            conn.close()

    barrier = threading.Barrier(2)
    results = {}

    def worker_task(worker_id):
        # Cada hilo debe abrir su propia conexión SQLite
        conn = get_db_connection(db_path)
        # Configurar busy_timeout para que SQLite espere en lugar de lanzar OperationalError
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            barrier.wait()  # Sincronizar el inicio de ambos hilos
            conn.execute("BEGIN IMMEDIATE")
            job = RefreshRunRepository.claim_job(conn, worker_id, lease_duration_seconds=30)
            conn.commit()
            results[worker_id] = job
        except Exception as e:
            results[worker_id] = e
        finally:
            conn.close()

    t1 = threading.Thread(target=worker_task, args=("worker-1",))
    t2 = threading.Thread(target=worker_task, args=("worker-2",))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Verificar que no hubo excepciones/bloqueos inesperados
    assert not isinstance(results.get("worker-1"), Exception), f"Worker 1 falló: {results.get('worker-1')}"
    assert not isinstance(results.get("worker-2"), Exception), f"Worker 2 falló: {results.get('worker-2')}"

    job1 = results["worker-1"]
    job2 = results["worker-2"]

    # Exactamente uno debió reclamar el trabajo, el otro debió obtener None
    if job1 is not None:
        assert job2 is None, "Ambos workers reclamaron el mismo trabajo"
        assert job1["id"] == 1
        assert job1["worker_id"] == "worker-1"
    else:
        assert job2 is not None, "Ningún worker reclamó el trabajo"
        assert job2["id"] == 1
        assert job2["worker_id"] == "worker-2"

    # Verificar el estado final en base de datos
    with app.app_context():
        conn = get_db_connection(db_path)
        try:
            run = conn.execute("SELECT status, worker_id FROM refresh_runs WHERE id = 1").fetchone()
            assert run["status"] == "running"
            assert run["worker_id"] in ("worker-1", "worker-2")
        finally:
            conn.close()
