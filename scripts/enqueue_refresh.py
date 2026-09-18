#!/usr/bin/env python3
import json

from flask import current_app

from app import create_app
from app.services.refresh_scheduler import DEFAULT_REFRESH_STAGES, enqueue_refresh


def main() -> int:
    app = create_app()
    with app.app_context():
        run_id = enqueue_refresh(current_app.config["DATABASE_PATH"])

    if run_id is None:
        print(json.dumps({"status": "skipped", "reason": "refresh_already_active"}))
    else:
        print(json.dumps({
            "status": "queued",
            "runId": run_id,
            "stages": list(DEFAULT_REFRESH_STAGES),
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
