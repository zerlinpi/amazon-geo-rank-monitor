from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .models import RankJobRow


class JobRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def enqueue(
        self,
        *,
        owner_id: str,
        provider_mode: str,
        request_payload: dict,
        monitor_target_id: str | None = None,
        job_id: str | None = None,
    ) -> dict:
        if provider_mode not in {"managed", "strict"}:
            raise ValueError("provider_mode must be managed or strict")
        job_id = job_id or str(uuid4())
        try:
            with self._sessions.begin() as session:
                session.add(
                    RankJobRow(
                        id=job_id,
                        owner_id=owner_id,
                        monitor_target_id=monitor_target_id,
                        provider_mode=provider_mode,
                        request_payload=request_payload,
                        status="pending",
                    )
                )
        except IntegrityError:
            existing = self.get(job_id, owner_id=owner_id)
            if (
                existing["monitor_target_id"] != monitor_target_id
                or existing["provider_mode"] != provider_mode
            ):
                raise ValueError("job id already exists with different parameters") from None
            return existing
        return self.get(job_id, owner_id=owner_id)

    def claim_one(self) -> dict | None:
        if self._engine.dialect.name == "postgresql":
            return self._claim_one_postgresql()
        return self._claim_one_compare_and_swap()

    def _claim_one_postgresql(self) -> dict | None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(RankJobRow)
                .where(RankJobRow.status == "pending")
                .order_by(RankJobRow.created_at, RankJobRow.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = "running"
            row.claimed_at = datetime.now(UTC)
            row.attempt_count += 1
            session.flush()
            return self._serialize(row)

    def _claim_one_compare_and_swap(self) -> dict | None:
        with self._sessions.begin() as session:
            candidate = session.scalar(
                select(RankJobRow.id)
                .where(RankJobRow.status == "pending")
                .order_by(RankJobRow.created_at, RankJobRow.id)
                .limit(1)
            )
            if candidate is None:
                return None
            now = datetime.now(UTC)
            result = session.execute(
                update(RankJobRow)
                .where(
                    RankJobRow.id == candidate,
                    RankJobRow.status == "pending",
                )
                .values(
                    status="running",
                    claimed_at=now,
                    attempt_count=RankJobRow.attempt_count + 1,
                )
            )
            if result.rowcount != 1:
                return None
            row = session.get(RankJobRow, candidate)
            return self._serialize(row)

    def complete(
        self,
        job_id: str,
        *,
        run_id: str,
        status: str = "succeeded",
    ) -> dict:
        if status not in {"succeeded", "partially_succeeded", "failed", "cancelled"}:
            raise ValueError(f"unsupported terminal job status: {status}")
        with self._sessions.begin() as session:
            row = session.get(RankJobRow, job_id)
            if row is None:
                raise KeyError(f"rank job not found: {job_id}")
            row.status = status
            row.run_id = run_id
            row.completed_at = datetime.now(UTC)
            row.error = None
            owner_id = row.owner_id
        return self.get(job_id, owner_id=owner_id)

    def fail(self, job_id: str, *, error: str) -> dict:
        with self._sessions.begin() as session:
            row = session.get(RankJobRow, job_id)
            if row is None:
                raise KeyError(f"rank job not found: {job_id}")
            row.status = "failed"
            row.error = error
            row.completed_at = datetime.now(UTC)
            owner_id = row.owner_id
        return self.get(job_id, owner_id=owner_id)

    def get(self, job_id: str, *, owner_id: str) -> dict:
        with self._sessions() as session:
            row = session.scalar(
                select(RankJobRow).where(
                    RankJobRow.id == job_id,
                    RankJobRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise KeyError(f"rank job not found: {job_id}")
            return self._serialize(row)

    def list_for_monitor(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        limit: int = 50,
    ) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(RankJobRow)
                .where(
                    RankJobRow.owner_id == owner_id,
                    RankJobRow.monitor_target_id == monitor_target_id,
                )
                .order_by(RankJobRow.created_at.desc(), RankJobRow.id.desc())
                .limit(limit)
            ).all()
            return [self._serialize(row) for row in rows]

    @staticmethod
    def _serialize(row: RankJobRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "monitor_target_id": row.monitor_target_id,
            "provider_mode": row.provider_mode,
            "request_payload": row.request_payload,
            "status": row.status,
            "claimed_at": row.claimed_at,
            "completed_at": row.completed_at,
            "run_id": row.run_id,
            "error": row.error,
            "attempt_count": row.attempt_count,
            "created_at": row.created_at,
        }
