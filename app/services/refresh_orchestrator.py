import json

from app.repositories.refresh_run_repository import RefreshRunRepository
from app.services.discovery_service import DiscoveryService
from app.services.subscription_service import SubscriptionService
from app.services.video_service import VideoService


class RefreshOrchestrator:
    def __init__(self, gateway=None):
        self.gateway = gateway

    def run_refresh(self, db, run_id: int, worker_id: str):
        """Ejecuta una corrida de actualización paso a paso."""
        import logging

        from flask import current_app

        from app.db import get_db_connection

        logger = logging.getLogger(__name__)
        db_path = current_app.config["DATABASE_PATH"]

        # Define a heartbeat callback that extends the lease and checks ownership
        def heartbeat_callback():
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

        # 1. Obtener la corrida de la base de datos
        run = RefreshRunRepository.get_by_id(db, run_id)
        if not run:
            raise ValueError(f"No existe la ejecución de actualización con ID: {run_id}")

        stages = json.loads(run["requested_stages_json"])
        counters = {}
        errors = {}

        has_success = False
        has_failure = False

        for stage in stages:
            # 2. Registrar el progreso de la etapa actual en una conexión corta separada
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

            try:
                # Nos aseguramos de revertir cualquier estado pendiente en db
                db.rollback()

                # Verificar si seguimos teniendo el lease antes de empezar la etapa
                heartbeat_callback()

                if stage == "subscriptions":
                    sub_service = SubscriptionService(gateway=self.gateway)
                    stats = sub_service.sync_subscriptions(db, heartbeat_callback=heartbeat_callback)
                    db.commit()
                    counters["subscriptions"] = stats
                    has_success = True

                elif stage == "followed_videos":
                    video_service = VideoService(gateway=self.gateway)
                    stats = video_service.sync_videos(db, heartbeat_callback=heartbeat_callback)
                    db.commit()
                    counters["followed_videos"] = stats
                    has_success = True

                elif stage == "discovery":
                    discovery_service = DiscoveryService(gateway=self.gateway)
                    stats = discovery_service.run_discovery(db, run_id=run_id, heartbeat_callback=heartbeat_callback)
                    counters["discovery"] = stats

                    # Comprobar si alguna categoría falló en su lote de descubrimiento
                    failed_cats = [cid for cid, cat_stat in stats["categories"].items() if cat_stat.get("failed")]
                    if failed_cats:
                        errors["discovery"] = f"El descubrimiento falló para las categorías: {failed_cats}"
                        has_failure = True
                    else:
                        has_success = True

                else:
                    errors[stage] = f"Etapa desconocida: {stage}"
                    has_failure = True

            except Exception as e:
                db.rollback() # Rollback de cualquier cambio de negocio parcial
                logger.exception(f"Error al ejecutar etapa {stage}:")
                # Sanitizar error (no tracebacks expuestos al cliente)
                errors[stage] = f"Error en la etapa {stage}: {str(e)}"
                has_failure = True

            # Actualizar heartbeat al finalizar cada etapa en conexión corta
            try:
                heartbeat_callback()
            except Exception as se:
                logger.error(f"Error extending lease heartbeat: {se}")

        # 3. Finalizar la corrida determinando el estado
        if has_failure:
            if has_success:
                final_status = "partial"
            else:
                final_status = "failed"
        else:
            final_status = "succeeded"

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
