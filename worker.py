import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from app.config import get_config
from app.db import get_db_connection

# Generar un ID único para esta instancia de worker
WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"
LEASE_DURATION_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 10

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
        # 1. Uno en estado 'pending'
        # 2. O uno en estado 'running' cuyo lease_expires_at sea menor que el momento actual (abandonado)
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

def update_heartbeat(db_path, job_id):
    """Actualiza el heartbeat y extiende el lease de una ejecución activa."""
    conn = get_db_connection(db_path)
    now = get_utc_now_iso()
    lease_expiry = (datetime.now(timezone.utc) + timedelta(seconds=LEASE_DURATION_SECONDS)).isoformat()

    try:
        conn.execute("""
            UPDATE refresh_runs
            SET heartbeat_at = ?,
                lease_expires_at = ?
            WHERE id = ? AND worker_id = ? AND status = 'running'
        """, (now, lease_expiry, job_id, WORKER_ID))
        conn.commit()
        return True
    except Exception as e:
        print(f"[{WORKER_ID}] Error al actualizar heartbeat del trabajo #{job_id}: {e}")
        return False
    finally:
        conn.close()

def finish_job(db_path, job_id, status, counters=None, errors=None):
    """Marca la ejecución de actualización como finalizada (succeeded, failed, partial)."""
    conn = get_db_connection(db_path)
    now = get_utc_now_iso()
    counters_json = json.dumps(counters or {})
    errors_json = json.dumps(errors or [])

    try:
        conn.execute("""
            UPDATE refresh_runs
            SET status = ?,
                finished_at = ?,
                counters_json = ?,
                errors_json = ?,
                lease_expires_at = NULL
            WHERE id = ? AND worker_id = ?
        """, (status, now, counters_json, errors_json, job_id, WORKER_ID))
        conn.commit()
        print(f"[{WORKER_ID}] Trabajo #{job_id} finalizado con estado: {status}")
    except Exception as e:
        print(f"[{WORKER_ID}] Error al finalizar el trabajo #{job_id}: {e}")
    finally:
        conn.close()

def process_job(db_path, job):
    """Simula el procesamiento de una actualización en Fase 0."""
    job_id = job["id"]
    stages = job["stages"]
    print(f"[{WORKER_ID}] Procesando trabajo #{job_id} con etapas: {stages}")

    # Simular la ejecución de cada etapa y el envío de heartbeats
    counters = {}
    errors = []

    # Definir etapas por defecto si no se especifican
    default_stages = ["subscriptions", "channels", "followed_videos", "classification", "discovery"]
    active_stages = stages if stages else default_stages

    for stage in active_stages:
        print(f"[{WORKER_ID}] Ejecutando etapa: {stage}...")

        # Guardar en base de datos la etapa actual
        conn = get_db_connection(db_path)
        try:
            conn.execute("UPDATE refresh_runs SET current_stage = ? WHERE id = ?", (stage, job_id))
            conn.commit()
        except Exception as e:
            print(f"Error al actualizar la etapa actual: {e}")
        finally:
            conn.close()

        # Simular trabajo
        time.sleep(2)

        # Simular contador de resultados para Fase 0
        counters[f"{stage}_processed"] = 10

        # Enviar heartbeat
        update_heartbeat(db_path, job_id)

    # Finalizar exitosamente
    finish_job(db_path, job_id, "succeeded", counters, errors)

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
