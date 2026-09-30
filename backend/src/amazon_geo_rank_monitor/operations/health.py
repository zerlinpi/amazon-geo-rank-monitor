"""Compose worker/scheduler health check; emits no connection strings or secrets."""

import os
import sys
from datetime import UTC, datetime

from sqlalchemy import create_engine, select

from amazon_geo_rank_monitor.repositories.models import WorkerHeartbeatRow


def main():
    kind = sys.argv[1]
    identity = os.environ["WORKER_ID" if kind == "rank" else "SCHEDULER_ID"]
    poll = float(
        os.getenv("WORKER_POLL_SECONDS" if kind == "rank" else "SCHEDULER_POLL_SECONDS", "30")
    )
    engine = create_engine(os.environ["DATABASE_URL"], connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            row = connection.execute(
                select(
                    WorkerHeartbeatRow.last_seen_at,
                    WorkerHeartbeatRow.status,
                ).where(
                    WorkerHeartbeatRow.worker_id == identity, WorkerHeartbeatRow.worker_type == kind
                )
            ).first()
        if not row:
            return 1
        stamp = (
            row.last_seen_at.replace(tzinfo=UTC)
            if row.last_seen_at.tzinfo is None
            else row.last_seen_at
        )
        return int(
            (datetime.now(UTC) - stamp).total_seconds() > max(poll * 3, 90) or row.status == "error"
        )
    except Exception:
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
