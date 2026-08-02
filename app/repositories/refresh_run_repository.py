import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


class RefreshRunRepository:
    @staticmethod
    def create(db, requested_stages: List[str]) -> int:
        """Crea una nueva ejecución de actualización en estado pending."""
        now = datetime.now(timezone.utc).isoformat()
        stages_json = json.dumps(requested_stages)
        counters_json = json.dumps({})
        errors_json = json.dumps({})

        cursor = db.execute("""
            INSERT INTO refresh_runs (
                status, requested_stages_json, current_stage, requested_at,
                counters_json, errors_json
            ) VALUES ('pending', ?, NULL, ?, ?, ?)
        """, (stages_json, now, counters_json, errors_json))
        return cursor.lastrowid

    @staticmethod
    def list_all(db) -> List[Dict[str, Any]]:
        """Lista todas las ejecuciones ordenadas por fecha de solicitud desc."""
        cursor = db.execute("""
            SELECT id, status, requested_stages_json, current_stage, requested_at,
                   started_at, finished_at, counters_json, errors_json,
                   heartbeat_at, lease_expires_at, worker_id
            FROM refresh_runs
            ORDER BY requested_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_id(db, run_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene una ejecución por su ID."""
        cursor = db.execute("""
            SELECT id, status, requested_stages_json, current_stage, requested_at,
                   started_at, finished_at, counters_json, errors_json,
                   heartbeat_at, lease_expires_at, worker_id
            FROM refresh_runs
            WHERE id = ?
        """, (run_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def has_active_run(db) -> bool:
        """Retorna True si hay alguna ejecución pending o running (con lease vigente)."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = db.execute("""
            SELECT 1 FROM refresh_runs
            WHERE status = 'pending'
               OR (status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at > ?))
        """, (now,))
        return cursor.fetchone() is not None

    @staticmethod
    def claim_job(db, worker_id: str, lease_duration_seconds: int = 60) -> Optional[Dict[str, Any]]:
        """
        Reclama atómicamente un trabajo pendiente o uno cuya lease haya expirado.
        Retorna el registro del trabajo reclamado o None si no hay ninguno.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        lease_expires = (now + timedelta(seconds=lease_duration_seconds)).isoformat()

        # Buscar candidato eligible
        # 1. pending
        # 2. running pero lease expirado
        cursor = db.execute("""
            SELECT id, status, lease_expires_at FROM refresh_runs
            WHERE status = 'pending'
               OR (status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
            ORDER BY requested_at ASC
            LIMIT 1
        """, (now_iso,))
        row = cursor.fetchone()
        if not row:
            return None

        run_id = row["id"]
        status = row["status"]

        if status == 'pending':
            # Reclamar pendiente
            db.execute("""
                UPDATE refresh_runs
                SET status = 'running', worker_id = ?, started_at = ?, heartbeat_at = ?, lease_expires_at = ?
                WHERE id = ? AND status = 'pending'
            """, (worker_id, now_iso, now_iso, lease_expires, run_id))
        else:
            # Reclamar lease vencido
            db.execute("""
                UPDATE refresh_runs
                SET status = 'running', worker_id = ?, heartbeat_at = ?, lease_expires_at = ?
                WHERE id = ? AND status = 'running' AND lease_expires_at = ?
            """, (worker_id, now_iso, lease_expires, run_id, row["lease_expires_at"]))

        # Retornar el registro actualizado si se pudo reclamar
        return RefreshRunRepository.get_by_id(db, run_id)

    @staticmethod
    def update_heartbeat(db, run_id: int, worker_id: str, lease_duration_seconds: int = 60) -> bool:
        """Actualiza el heartbeat y extiende el lease si el worker sigue siendo el propietario."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        lease_expires = (now + timedelta(seconds=lease_duration_seconds)).isoformat()

        cursor = db.execute("""
            UPDATE refresh_runs
            SET heartbeat_at = ?, lease_expires_at = ?
            WHERE id = ? AND worker_id = ? AND status = 'running'
        """, (now_iso, lease_expires, run_id, worker_id))
        return cursor.rowcount > 0

    @staticmethod
    def update_stage_progress(db, run_id: int, worker_id: str, stage: str, counters: dict, errors: dict) -> bool:
        """Actualiza el progreso de la etapa actual."""
        cursor = db.execute("""
            UPDATE refresh_runs
            SET current_stage = ?, counters_json = ?, errors_json = ?
            WHERE id = ? AND worker_id = ? AND status = 'running'
        """, (stage, json.dumps(counters), json.dumps(errors), run_id, worker_id))
        return cursor.rowcount > 0

    @staticmethod
    def finish(db, run_id: int, worker_id: str, final_status: str, counters: dict, errors: dict) -> bool:
        """Finaliza la ejecución con estado terminado (finished, partial, failed)."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = db.execute("""
            UPDATE refresh_runs
            SET status = ?, finished_at = ?, current_stage = NULL, counters_json = ?, errors_json = ?
            WHERE id = ? AND worker_id = ? AND status = 'running'
        """, (final_status, now, json.dumps(counters), json.dumps(errors), run_id, worker_id))
        return cursor.rowcount > 0
