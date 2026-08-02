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
        # 1. Obtener la corrida de la base de datos
        run = RefreshRunRepository.get_by_id(db, run_id)
        if not run:
            raise ValueError(f"No existe la ejecución de actualización con ID: {run_id}")

        stages = json.loads(run["requested_stages_json"])
        counters = {}
        errors = {}

        # Guardar estado actual
        has_success = False
        has_failure = False

        for stage in stages:
            # 2. Registrar el progreso de la etapa actual
            RefreshRunRepository.update_stage_progress(db, run_id, worker_id, stage, counters, errors)
            # Actualizar heartbeat
            RefreshRunRepository.update_heartbeat(db, run_id, worker_id)
            db.commit()

            try:
                if stage == "subscriptions":
                    sub_service = SubscriptionService(gateway=self.gateway)
                    stats = sub_service.sync_subscriptions(db)
                    counters["subscriptions"] = stats
                    has_success = True

                elif stage == "followed_videos":
                    video_service = VideoService(gateway=self.gateway)
                    stats = video_service.sync_videos(db)
                    counters["followed_videos"] = stats
                    has_success = True

                elif stage == "classification":
                    # Punto de extensión no implementado aún
                    errors["classification"] = "Clasificación automática no implementada en este incremento."
                    has_failure = True

                elif stage == "discovery":
                    discovery_service = DiscoveryService(gateway=self.gateway)
                    stats = discovery_service.run_discovery(db, run_id=run_id)
                    counters["discovery"] = stats
                    has_success = True

                else:
                    errors[stage] = f"Etapa desconocida: {stage}"
                    has_failure = True

            except Exception as e:
                import traceback
                error_msg = f"{str(e)}\n{traceback.format_exc()}"
                errors[stage] = error_msg
                has_failure = True

            # Actualizar heartbeat al finalizar cada etapa
            RefreshRunRepository.update_heartbeat(db, run_id, worker_id)
            db.commit()

        # 3. Finalizar la corrida determinando el estado
        if has_failure:
            if has_success:
                final_status = "partial"
            else:
                final_status = "failed"
        else:
            final_status = "succeeded"

        RefreshRunRepository.finish(db, run_id, worker_id, final_status, counters, errors)
        db.commit()
