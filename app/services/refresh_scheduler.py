from collections.abc import Sequence
from typing import Optional

from app.db import get_db_connection
from app.repositories.refresh_run_repository import RefreshRunRepository

DEFAULT_REFRESH_STAGES = ("subscriptions", "followed_videos", "discovery")


def enqueue_refresh(db_path: str, stages: Sequence[str] = DEFAULT_REFRESH_STAGES) -> Optional[int]:
    """Encola una actualización si no existe otra pendiente o en ejecución."""
    db = get_db_connection(db_path)
    try:
        # Serializa el chequeo y la inserción para que dos disparadores simultáneos
        # no puedan crear trabajos duplicados.
        db.execute("BEGIN IMMEDIATE")
        if RefreshRunRepository.has_active_run(db):
            db.rollback()
            return None

        run_id = RefreshRunRepository.create(db, list(stages))
        db.commit()
        return run_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
