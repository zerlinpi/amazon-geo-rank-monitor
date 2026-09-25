from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .models import ReportDeliveryRow, ReportScheduleRow


class ReportRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def create_schedule(
        self,
        *,
        owner_id: str,
        name: str,
        monitor_target_ids: list[str],
        recipients_encrypted: str,
        schedule: str,
        lookback_hours: int,
        include_csv: bool,
        enabled: bool,
    ) -> dict:
        row = ReportScheduleRow(
            id=str(uuid4()),
            owner_id=owner_id,
            name=name,
            monitor_target_ids=monitor_target_ids,
            recipients_encrypted=recipients_encrypted,
            schedule=schedule,
            lookback_hours=lookback_hours,
            include_csv=include_csv,
            enabled=enabled,
        )
        with self._sessions.begin() as session:
            session.add(row)
            session.flush()
            return self._serialize_schedule(row)

    def get_schedule(self, *, owner_id: str, schedule_id: str) -> dict:
        with self._sessions() as session:
            row = session.scalar(
                select(ReportScheduleRow).where(
                    ReportScheduleRow.id == schedule_id,
                    ReportScheduleRow.owner_id == owner_id,
                    ReportScheduleRow.deleted_at.is_(None),
                )
            )
            if row is None:
                raise KeyError("report schedule not found")
            return self._serialize_schedule(row)

    def list_schedules(self, *, owner_id: str) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ReportScheduleRow)
                .where(
                    ReportScheduleRow.owner_id == owner_id,
                    ReportScheduleRow.deleted_at.is_(None),
                )
                .order_by(
                    ReportScheduleRow.created_at,
                    ReportScheduleRow.id,
                )
            ).all()
            return [self._serialize_schedule(row) for row in rows]

    def list_scheduled(self) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ReportScheduleRow)
                .where(
                    ReportScheduleRow.enabled.is_(True),
                    ReportScheduleRow.deleted_at.is_(None),
                )
                .order_by(
                    ReportScheduleRow.created_at,
                    ReportScheduleRow.id,
                )
            ).all()
            return [self._serialize_schedule(row) for row in rows]

    def update_schedule(
        self,
        *,
        owner_id: str,
        schedule_id: str,
        changes: dict,
    ) -> dict:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(ReportScheduleRow).where(
                    ReportScheduleRow.id == schedule_id,
                    ReportScheduleRow.owner_id == owner_id,
                    ReportScheduleRow.deleted_at.is_(None),
                )
            )
            if row is None:
                raise KeyError("report schedule not found")
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(UTC)
            session.flush()
            return self._serialize_schedule(row)

    def delete_schedule(self, *, owner_id: str, schedule_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(ReportScheduleRow).where(
                    ReportScheduleRow.id == schedule_id,
                    ReportScheduleRow.owner_id == owner_id,
                    ReportScheduleRow.deleted_at.is_(None),
                )
            )
            if row is None:
                raise KeyError("report schedule not found")
            row.enabled = False
            row.deleted_at = datetime.now(UTC)
            row.updated_at = datetime.now(UTC)

    def reserve_delivery(
        self,
        *,
        owner_id: str,
        schedule_id: str,
        scheduled_for: datetime,
        subject: str,
        recipient_count: int,
    ) -> dict | None:
        row = ReportDeliveryRow(
            id=str(uuid4()),
            owner_id=owner_id,
            schedule_id=schedule_id,
            scheduled_for=self._utc(scheduled_for),
            status="sending",
            recipient_count=recipient_count,
            sent_count=0,
            subject=subject,
            summary={},
        )
        try:
            with self._sessions.begin() as session:
                session.add(row)
                session.flush()
                return self._serialize_delivery(row)
        except IntegrityError:
            return None

    def complete_delivery(
        self,
        *,
        delivery_id: str,
        status: str,
        sent_count: int,
        summary: dict,
        error: str | None = None,
    ) -> dict:
        if status not in {"sent", "partially_failed", "failed"}:
            raise ValueError("unsupported report delivery status")
        with self._sessions.begin() as session:
            row = session.get(ReportDeliveryRow, delivery_id)
            if row is None:
                raise KeyError("report delivery not found")
            row.status = status
            row.sent_count = sent_count
            row.summary = summary
            row.error = str(error)[:8000] if error else None
            row.completed_at = datetime.now(UTC)
            session.flush()
            return self._serialize_delivery(row)

    def list_deliveries(
        self,
        *,
        owner_id: str,
        limit: int = 100,
    ) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ReportDeliveryRow)
                .where(ReportDeliveryRow.owner_id == owner_id)
                .order_by(
                    ReportDeliveryRow.scheduled_for.desc(),
                    ReportDeliveryRow.id.desc(),
                )
                .limit(min(max(limit, 1), 500))
            ).all()
            return [self._serialize_delivery(row) for row in rows]

    @staticmethod
    def _serialize_schedule(row: ReportScheduleRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "monitor_target_ids": list(row.monitor_target_ids or []),
            "recipients_encrypted": row.recipients_encrypted,
            "schedule": row.schedule,
            "lookback_hours": row.lookback_hours,
            "include_csv": row.include_csv,
            "enabled": row.enabled,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
        }

    @staticmethod
    def _serialize_delivery(row: ReportDeliveryRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "schedule_id": row.schedule_id,
            "scheduled_for": row.scheduled_for,
            "status": row.status,
            "recipient_count": row.recipient_count,
            "sent_count": row.sent_count,
            "subject": row.subject,
            "summary": row.summary,
            "error": row.error,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
        }

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
