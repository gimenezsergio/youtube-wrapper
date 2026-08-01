import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from app.config import get_config
from app.db import get_db_connection
from app.services.refresh_orchestrator import RefreshOrchestrator

# Generar un ID único para esta instancia de worker
WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"
LEASE_DURATION_SECONDS = 30

def get_utc_now_iso():
    """Retorna la fecha y hora UTC actual en formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat()

def claim_next_job(db_path):
    """
    Intenta reclamar el siguiente trabajo pendiente de actualización de forma atómica.
    También reclama ejecuciones abandonadas cuya lease haya expirado.
    """
    conn = get_db_connection(db_path)
    now = get_utc_now_iso()
    lease_expiry = (datetime.now(timezone.utc) + timedelta(seconds=LEASE_DURATION_SECONDS)).isoformat()

    try:
        # Usar BEGIN IMMEDIATE para bloquear la base de datos de manera segura y evitar colisiones de concurrencia
        conn.execute("BEGIN IMMEDIATE")

        # Buscar el siguiente trabajo candidato
        cursor = conn.execute("""
            SELECT id, status, requested_stages_json
            FROM refresh_runs
            WHERE status = 'pending'
               OR (status = 'running' AND datetime(lease_expires_at) < datetime(?))
            ORDER BY requested_at ASC
            LIMIT 1
        """, (now,))

        row = cursor.fetchone()
        if not row:
            conn.commit()
            return None

        job_id = row["id"]
        old_status = row["status"]
        stages = json.loads(row["requested_stages_json"])

        print(f"[{WORKER_ID}] Reclamando trabajo #{job_id} (estado anterior: {old_status})...")

        # Actualizar a 'running'
        conn.execute("""
            UPDATE refresh_runs
            SET status = 'running',
                started_at = CASE WHEN status = 'pending' THEN ? ELSE started_at END,
                heartbeat_at = ?,
                lease_expires_at = ?,
                worker_id = ?
            WHERE id = ?
        """, (now, now, lease_expiry, WORKER_ID, job_id))

        conn.commit()
        return {"id": job_id, "stages": stages}

    except Exception as e:
        conn.rollback()
        print(f"[{WORKER_ID}] Error al intentar reclamar trabajo: {e}")
        return None
    finally:
        conn.close()

def process_job(db_path, job):
    """Procesa una corrida de actualización usando el RefreshOrchestrator."""
    job_id = job["id"]
    print(f"[{WORKER_ID}] Procesando trabajo #{job_id} mediante RefreshOrchestrator...")
    
    conn = get_db_connection(db_path)
    try:
        orchestrator = RefreshOrchestrator()
        orchestrator.run_refresh(conn, job_id, WORKER_ID)
        conn.commit()
        print(f"[{WORKER_ID}] Trabajo #{job_id} completado con éxito.")
    except Exception as e:
        conn.rollback()
        print(f"[{WORKER_ID}] Error al procesar trabajo #{job_id}: {e}")
    finally:
        conn.close()

def main():
    config = get_config()
    db_path = config.DATABASE_PATH
    print(f"[{WORKER_ID}] Worker iniciado. Monitoreando base de datos: {db_path}")

    # Crear la tabla de refresh_runs si no existe (por seguridad)
    conn = get_db_connection(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS refresh_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            requested_stages_json TEXT,
            current_stage TEXT,
            requested_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            counters_json TEXT,
            errors_json TEXT,
            heartbeat_at TEXT,
            lease_expires_at TEXT,
            worker_id TEXT
        )
    """)
    conn.commit()
    conn.close()

    try:
        while True:
            job = claim_next_job(db_path)
            if job:
                process_job(db_path, job)
            else:
                # Esperar antes de la próxima consulta
                time.sleep(2)
    except KeyboardInterrupt:
        print(f"[{WORKER_ID}] Worker detenido por el usuario.")

if __name__ == "__main__":
    main()
