from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .models import RankJobRow


class JobRepository:
    def __init__(self, engine: Engine, *, default_max_attempts: int = 3) -> None:
        if default_max_attempts < 1:
            raise ValueError("default_max_attempts must be at least 1")
        self._engine = engine
        self._default_max_attempts = default_max_attempts
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def enqueue(
        self,
        *,
        owner_id: str,
        provider_mode: str,
        request_payload: dict,
        monitor_target_id: str | None = None,
        job_id: str | None = None,
        max_attempts: int | None = None,
        available_at: datetime | None = None,
    ) -> dict:
        if provider_mode not in {"managed", "strict"}:
            raise ValueError("provider_mode must be managed or strict")
        attempts = max_attempts or self._default_max_attempts
        if attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        job_id = job_id or str(uuid4())
        ready_at = self._utc(available_at or datetime.now(UTC))
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
                        available_at=ready_at,
                        max_attempts=attempts,
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

    def claim_one(
        self,
        *,
        worker_id: str = "rank-worker",
        lease_seconds: float = 900.0,
        now: datetime | None = None,
    ) -> dict | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = self._utc(now or datetime.now(UTC))
        if self._engine.dialect.name == "postgresql":
            return self._claim_one_postgresql(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                now=current,
            )
        return self._claim_one_compare_and_swap(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            now=current,
        )

    def _claim_one_postgresql(
        self,
        *,
        worker_id: str,
        lease_seconds: float,
        now: datetime,
    ) -> dict | None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(RankJobRow)
                .where(
                    RankJobRow.status == "pending",
                    RankJobRow.available_at <= now,
                )
                .order_by(RankJobRow.available_at, RankJobRow.created_at, RankJobRow.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            self._mark_claimed(
                row,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                now=now,
            )
            session.flush()
            return self._serialize(row)

    def _claim_one_compare_and_swap(
        self,
        *,
        worker_id: str,
        lease_seconds: float,
        now: datetime,
    ) -> dict | None:
        with self._sessions.begin() as session:
            candidate = session.scalar(
                select(RankJobRow.id)
                .where(
                    RankJobRow.status == "pending",
                    RankJobRow.available_at <= now,
                )
                .order_by(RankJobRow.available_at, RankJobRow.created_at, RankJobRow.id)
                .limit(1)
            )
            if candidate is None:
                return None
            result = session.execute(
                update(RankJobRow)
                .where(
                    RankJobRow.id == candidate,
                    RankJobRow.status == "pending",
                    RankJobRow.available_at <= now,
                )
                .values(
                    status="running",
                    claimed_at=now,
                    claimed_by=worker_id,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    attempt_count=RankJobRow.attempt_count + 1,
                )
            )
            if result.rowcount != 1:
                return None
            row = session.get(RankJobRow, candidate)
            return self._serialize(row)

    def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = self._utc(now or datetime.now(UTC))
        with self._sessions.begin() as session:
            result = session.execute(
                update(RankJobRow)
                .where(
                    RankJobRow.id == job_id,
                    RankJobRow.status == "running",
                    RankJobRow.claimed_by == worker_id,
                )
                .values(
                    lease_expires_at=current + timedelta(seconds=lease_seconds)
                )
            )
            return result.rowcount == 1

    def retry_or_dead_letter(
        self,
        job_id: str,
        *,
        error: str,
        base_delay_seconds: float = 30.0,
        max_delay_seconds: float = 900.0,
        now: datetime | None = None,
    ) -> dict:
        if base_delay_seconds < 0 or max_delay_seconds < 0:
            raise ValueError("retry delays must be non-negative")
        current = self._utc(now or datetime.now(UTC))
        with self._sessions.begin() as session:
            row = session.get(RankJobRow, job_id)
            if row is None:
                raise KeyError(f"rank job not found: {job_id}")
            if row.status != "running":
                raise ValueError("only running jobs can be retried")

            row.error = self._bounded_error(error)
            row.claimed_at = None
            row.claimed_by = None
            row.lease_expires_at = None
            owner_id = row.owner_id

            if row.attempt_count >= row.max_attempts:
                row.status = "dead_letter"
                row.completed_at = current
            else:
                exponent = max(row.attempt_count - 1, 0)
                delay = min(base_delay_seconds * (2**exponent), max_delay_seconds)
                row.status = "pending"
                row.available_at = current + timedelta(seconds=delay)
                row.completed_at = None

        return self.get(job_id, owner_id=owner_id)

    def recover_stale(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        current = self._utc(now or datetime.now(UTC))
        retried = 0
        dead_lettered = 0
        with self._sessions.begin() as session:
            statement = (
                select(RankJobRow)
                .where(
                    RankJobRow.status == "running",
                    RankJobRow.lease_expires_at.is_not(None),
                    RankJobRow.lease_expires_at <= current,
                )
                .order_by(RankJobRow.lease_expires_at, RankJobRow.id)
            )
            if self._engine.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            rows = session.scalars(statement).all()
            for row in rows:
                row.error = self._bounded_error("worker lease expired")
                row.claimed_at = None
                row.claimed_by = None
                row.lease_expires_at = None
                if row.attempt_count >= row.max_attempts:
                    row.status = "dead_letter"
                    row.completed_at = current
                    dead_lettered += 1
                else:
                    row.status = "pending"
                    row.available_at = current
                    row.completed_at = None
                    retried += 1
        return {"retried": retried, "dead_lettered": dead_lettered}

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
            row.claimed_by = None
            row.lease_expires_at = None
            owner_id = row.owner_id
        return self.get(job_id, owner_id=owner_id)

    def fail(self, job_id: str, *, error: str) -> dict:
        with self._sessions.begin() as session:
            row = session.get(RankJobRow, job_id)
            if row is None:
                raise KeyError(f"rank job not found: {job_id}")
            row.status = "failed"
            row.error = self._bounded_error(error)
            row.completed_at = datetime.now(UTC)
            row.claimed_by = None
            row.lease_expires_at = None
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

    def queue_summary(self) -> dict:
        with self._sessions() as session:
            counts = {
                status: count
                for status, count in session.execute(
                    select(RankJobRow.status, func.count(RankJobRow.id)).group_by(
                        RankJobRow.status
                    )
                ).all()
            }
            oldest_pending_at = session.scalar(
                select(func.min(RankJobRow.available_at)).where(
                    RankJobRow.status == "pending"
                )
            )
        return {
            "counts": counts,
            "oldest_pending_at": oldest_pending_at,
        }

    @staticmethod
    def _mark_claimed(
        row: RankJobRow,
        *,
        worker_id: str,
        lease_seconds: float,
        now: datetime,
    ) -> None:
        row.status = "running"
        row.claimed_at = now
        row.claimed_by = worker_id
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        row.attempt_count += 1

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _bounded_error(error: str) -> str:
        return str(error)[:8000]

    @staticmethod
    def _serialize(row: RankJobRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "monitor_target_id": row.monitor_target_id,
            "provider_mode": row.provider_mode,
            "request_payload": row.request_payload,
            "status": row.status,
            "available_at": row.available_at,
            "claimed_at": row.claimed_at,
            "claimed_by": row.claimed_by,
            "lease_expires_at": row.lease_expires_at,
            "completed_at": row.completed_at,
            "run_id": row.run_id,
            "error": row.error,
            "attempt_count": row.attempt_count,
            "max_attempts": row.max_attempts,
            "created_at": row.created_at,
        }
