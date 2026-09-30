"""Compose worker/scheduler health check; emits no connection strings or secrets."""

import logging
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Event, Thread

from sqlalchemy import create_engine, select

from amazon_geo_rank_monitor.repositories.models import WorkerHeartbeatRow

HEARTBEAT_INTERVAL_SECONDS = 30.0


@contextmanager
def keep_worker_alive(repository, worker_id: str):
    """Refresh liveness even while synchronous report/provider calls are busy."""
    if repository is None:
        yield
        return
    stopped = Event()

    def refresh():
        while not stopped.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                repository.refresh_heartbeat(worker_id)
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "heartbeat_refresh_failed worker_id=%s error_type=%s",
                    worker_id, type(exc).__name__,
                )

    thread = Thread(target=refresh, name=f"heartbeat-{worker_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=5)


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
