import time
import uuid

from flask import current_app

from app import create_app
from app.db import get_db_connection
from app.repositories.refresh_run_repository import RefreshRunRepository
from app.services.refresh_orchestrator import RefreshOrchestrator

# Generar un ID único para esta instancia de worker
WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"
LEASE_DURATION_SECONDS = 30

def main():
    app = create_app()
    with app.app_context():
        db_path = current_app.config["DATABASE_PATH"]
        print(f"[{WORKER_ID}] Worker iniciado. Monitoreando base de datos: {db_path}")

        try:
            while True:
                conn = get_db_connection(db_path)
                job = None
                try:
                    # BEGIN IMMEDIATE para evitar problemas de concurrencia y transacciones bloqueadas
                    conn.execute("BEGIN IMMEDIATE")
                    job = RefreshRunRepository.claim_job(conn, worker_id=WORKER_ID, lease_duration_seconds=LEASE_DURATION_SECONDS)
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"[{WORKER_ID}] Error al intentar reclamar trabajo: {e}")
                finally:
                    conn.close()

                if job:
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
                else:
                    # Esperar antes de la próxima consulta
                    time.sleep(2)
        except KeyboardInterrupt:
            print(f"[{WORKER_ID}] Worker detenido por el usuario.")

if __name__ == "__main__":
    main()
