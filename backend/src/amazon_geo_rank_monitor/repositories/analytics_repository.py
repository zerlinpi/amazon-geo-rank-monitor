from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from .models import (
    RankJobRow,
    RankObservationRow,
    RankRunRow,
    RankSnapshotRow,
)


COMPLETED_JOB_STATUSES = ("succeeded", "partially_succeeded")


class AnalyticsRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def aggregate_points(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        since: datetime,
        until: datetime,
        asin: str | None = None,
    ) -> list[dict]:
        statement = (
            select(
                RankRunRow.id,
                RankRunRow.completed_at,
                RankRunRow.status,
                RankSnapshotRow.asin,
                RankSnapshotRow.weighted_rank,
                RankSnapshotRow.found_weight,
                RankSnapshotRow.missing_weight,
                RankSnapshotRow.confidence,
            )
            .join(RankRunRow, RankRunRow.id == RankJobRow.run_id)
            .join(
                RankSnapshotRow,
                RankSnapshotRow.rank_run_id == RankRunRow.id,
            )
            .where(
                RankJobRow.owner_id == owner_id,
                RankJobRow.monitor_target_id == monitor_target_id,
                RankJobRow.status.in_(COMPLETED_JOB_STATUSES),
                RankRunRow.owner_id == owner_id,
                RankRunRow.completed_at.is_not(None),
                RankRunRow.completed_at >= self._utc(since),
                RankRunRow.completed_at <= self._utc(until),
            )
            .order_by(
                RankRunRow.completed_at,
                RankRunRow.id,
                RankSnapshotRow.asin,
            )
        )
        if asin:
            statement = statement.where(RankSnapshotRow.asin == asin.upper())

        with self._sessions() as session:
            rows = session.execute(statement).all()
        return [
            {
                "run_id": row.id,
                "completed_at": row.completed_at,
                "run_status": row.status,
                "asin": row.asin,
                "weighted_rank": row.weighted_rank,
                "found_weight": row.found_weight,
                "missing_weight": row.missing_weight,
                "confidence": row.confidence,
            }
            for row in rows
        ]

    def geo_points(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        since: datetime,
        until: datetime,
        asin: str | None = None,
        geo_profile_id: str | None = None,
    ) -> list[dict]:
        statement = (
            select(
                RankRunRow.id,
                RankRunRow.completed_at,
                RankRunRow.status,
                RankObservationRow.asin,
                RankObservationRow.geo_profile_id,
                RankObservationRow.found,
                RankObservationRow.organic_rank,
                RankObservationRow.absolute_rank,
                RankObservationRow.sponsored_rank,
                RankObservationRow.effective_rank,
                RankObservationRow.provider,
                RankObservationRow.verification_level,
            )
            .join(RankRunRow, RankRunRow.id == RankJobRow.run_id)
            .join(
                RankObservationRow,
                RankObservationRow.rank_run_id == RankRunRow.id,
            )
            .where(
                RankJobRow.owner_id == owner_id,
                RankJobRow.monitor_target_id == monitor_target_id,
                RankJobRow.status.in_(COMPLETED_JOB_STATUSES),
                RankRunRow.owner_id == owner_id,
                RankRunRow.completed_at.is_not(None),
                RankRunRow.completed_at >= self._utc(since),
                RankRunRow.completed_at <= self._utc(until),
            )
            .order_by(
                RankRunRow.completed_at,
                RankRunRow.id,
                RankObservationRow.asin,
                RankObservationRow.geo_profile_id,
            )
        )
        if asin:
            statement = statement.where(RankObservationRow.asin == asin.upper())
        if geo_profile_id:
            statement = statement.where(
                RankObservationRow.geo_profile_id == geo_profile_id
            )

        with self._sessions() as session:
            rows = session.execute(statement).all()
        return [
            {
                "run_id": row.id,
                "completed_at": row.completed_at,
                "run_status": row.status,
                "asin": row.asin,
                "geo_profile_id": row.geo_profile_id,
                "found": row.found,
                "organic_rank": row.organic_rank,
                "absolute_rank": row.absolute_rank,
                "sponsored_rank": row.sponsored_rank,
                "effective_rank": row.effective_rank,
                "provider": row.provider,
                "verification_level": row.verification_level,
            }
            for row in rows
        ]

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
