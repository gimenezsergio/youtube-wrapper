import json
import logging

from app.integrations.youtube.gateway import YouTubeQuotaError
from app.repositories.refresh_run_repository import RefreshRunRepository
from app.services.discovery_service import DiscoveryService
from app.services.subscription_service import SubscriptionService
from app.services.video_service import VideoService

logger = logging.getLogger(__name__)


def _send_heartbeat(db_path: str, run_id: int, worker_id: str):
    """Actualiza el heartbeat y verifica la propiedad del lease."""
    from app.db import get_db_connection

    state_conn = get_db_connection(db_path)
    try:
        state_conn.execute("BEGIN IMMEDIATE")
        still_owner = RefreshRunRepository.update_heartbeat(state_conn, run_id, worker_id)
        state_conn.commit()
        if not still_owner:
            logger.warning(f"[{worker_id}] Perdió la propiedad del lease para run #{run_id}.")
            raise Exception("Lease perdido. Interrupción segura.")
    except Exception as e:
        state_conn.rollback()
        raise e
    finally:
        state_conn.close()


def _record_stage_progress(db_path: str, run_id: int, worker_id: str, stage: str, counters: dict, errors: list):
    """Registra el progreso de etapa en una conexión SQLite corta."""
    from app.db import get_db_connection

    state_conn = get_db_connection(db_path)
    try:
        state_conn.execute("BEGIN IMMEDIATE")
        RefreshRunRepository.update_stage_progress(state_conn, run_id, worker_id, stage, counters, errors)
        RefreshRunRepository.update_heartbeat(state_conn, run_id, worker_id)
        state_conn.commit()
    except Exception as se:
        state_conn.rollback()
        logger.error(f"Error updating run status: {se}")
    finally:
        state_conn.close()


def _finish_refresh_run(
    db_path: str, run_id: int, worker_id: str, final_status: str, counters: dict, errors: list
):
    """Finaliza la corrida guardando estado, contadores y errores."""
    from app.db import get_db_connection

    state_conn = get_db_connection(db_path)
    try:
        state_conn.execute("BEGIN IMMEDIATE")
        RefreshRunRepository.finish(state_conn, run_id, worker_id, final_status, counters, errors)
        state_conn.commit()
    except Exception as se:
        state_conn.rollback()
        logger.error(f"Error finishing run: {se}")
    finally:
        state_conn.close()


class RefreshOrchestrator:
    def __init__(self, gateway=None):
        self.gateway = gateway

    def _execute_stage(self, stage: str, db, run_id: int, heartbeat_callback) -> tuple:
        """Ejecuta una etapa individual y retorna (stats, errors, has_success, has_failure)."""
        counters_entry = None
        errors_entry = []
        has_success = False
        has_failure = False

        if stage == "subscriptions":
            sub_service = SubscriptionService(gateway=self.gateway)
            counters_entry = sub_service.sync_subscriptions(db, heartbeat_callback=heartbeat_callback)
            db.commit()
            has_success = True

        elif stage == "followed_videos":
            video_service = VideoService(gateway=self.gateway)
            counters_entry = video_service.sync_videos(db, heartbeat_callback=heartbeat_callback)
            db.commit()
            has_success = True

        elif stage == "discovery":
            discovery_service = DiscoveryService(gateway=self.gateway)
            stats = discovery_service.run_discovery(db, run_id=run_id, heartbeat_callback=heartbeat_callback)
            disc_errors = stats.get("errors", [])
            if disc_errors:
                errors_entry.extend(disc_errors)

            counters_entry = {
                "searchesExecuted": stats.get("searches_executed", 0),
                "quotaExhausted": stats.get("quota_exhausted", False),
                "categories": stats.get("categories", {}),
            }

            cats = stats.get("categories", {})
            succeeded_cats = [cid for cid, cat_stat in cats.items() if not cat_stat.get("failed")]
            failed_cats = [cid for cid, cat_stat in cats.items() if cat_stat.get("failed")]

            if succeeded_cats:
                has_success = True
            if failed_cats:
                has_failure = True
                if not disc_errors:
                    errors_entry.append({
                        "stage": "discovery",
                        "code": "EXTERNAL_ERROR",
                        "message": f"El descubrimiento falló para las categorías: {failed_cats}",
                    })
        else:
            errors_entry.append({"stage": stage, "code": "UNKNOWN_STAGE", "message": f"Etapa desconocida: {stage}"})
            has_failure = True

        return counters_entry, errors_entry, has_success, has_failure

    def run_refresh(self, db, run_id: int, worker_id: str):
        """Ejecuta una corrida de actualización paso a paso."""
        from flask import current_app

        db_path = current_app.config["DATABASE_PATH"]
        def heartbeat_callback():
            _send_heartbeat(db_path, run_id, worker_id)

        run = RefreshRunRepository.get_by_id(db, run_id)
        if not run:
            raise ValueError(f"No existe la ejecución de actualización con ID: {run_id}")

        stages = json.loads(run["requested_stages_json"])
        counters = {}
        errors = []
        has_success = False
        has_failure = False

        for stage in stages:
            _record_stage_progress(db_path, run_id, worker_id, stage, counters, errors)

            try:
                db.rollback()
                heartbeat_callback()

                c_entry, e_entry, h_succ, h_fail = self._execute_stage(stage, db, run_id, heartbeat_callback)
                if c_entry is not None:
                    counters[stage] = c_entry
                if e_entry:
                    errors.extend(e_entry)
                if h_succ:
                    has_success = True
                if h_fail:
                    has_failure = True

            except Exception as e:
                db.rollback()
                logger.exception(f"Error al ejecutar etapa {stage}:")
                err_code = "YOUTUBE_QUOTA_EXHAUSTED" if isinstance(e, YouTubeQuotaError) else "EXTERNAL_ERROR"
                errors.append({"stage": stage, "code": err_code, "message": f"Error en la etapa {stage}: {str(e)}"})
                has_failure = True

            try:
                heartbeat_callback()
            except Exception as se:
                logger.error(f"Error extending lease heartbeat: {se}")

        final_status = "partial" if (has_failure and has_success) else ("failed" if has_failure else "succeeded")
        _finish_refresh_run(db_path, run_id, worker_id, final_status, counters, errors)
