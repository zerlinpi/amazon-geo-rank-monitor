from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from .models import WorkerHeartbeatRow


class WorkerStatusRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def heartbeat(
        self,
        *,
        worker_id: str,
        worker_type: str = "rank",
        status: str,
        last_job_id: str | None = None,
        last_error: str | None = None,
        processed_delta: int = 0,
    ) -> dict:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.get(WorkerHeartbeatRow, worker_id)
            if row is None:
                row = WorkerHeartbeatRow(
                    worker_id=worker_id,
                    worker_type=worker_type,
                    status=status,
                    last_job_id=last_job_id,
                    last_error=last_error,
                    processed_jobs=max(processed_delta, 0),
                    started_at=now,
                    last_seen_at=now,
                )
                session.add(row)
            else:
                row.worker_type = worker_type
                row.status = status
                row.last_job_id = last_job_id
                row.last_error = last_error
                row.processed_jobs += max(processed_delta, 0)
                row.last_seen_at = now
            session.flush()
            return self._serialize(row)

    def list(self) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(WorkerHeartbeatRow).order_by(
                    WorkerHeartbeatRow.last_seen_at.desc(),
                    WorkerHeartbeatRow.worker_id,
                )
            ).all()
            return [self._serialize(row) for row in rows]

    @staticmethod
    def _serialize(row: WorkerHeartbeatRow) -> dict:
        return {
            "worker_id": row.worker_id,
            "worker_type": row.worker_type,
            "status": row.status,
            "last_job_id": row.last_job_id,
            "last_error": row.last_error,
            "processed_jobs": row.processed_jobs,
            "started_at": row.started_at,
            "last_seen_at": row.last_seen_at,
        }
