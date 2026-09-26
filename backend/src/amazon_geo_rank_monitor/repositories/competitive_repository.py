from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, and_, select
from sqlalchemy.orm import sessionmaker

from .models import (
    RankJobRow,
    RankRunRow,
    SerpCompetitiveObservationRow,
)

COMPLETED_JOB_STATUSES = {"succeeded", "partially_succeeded"}


class CompetitiveRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def save_probe(
        self,
        *,
        owner_id: str,
        run_id: str,
        geo_profile_id: str,
        rows: list[dict],
        probe_source: str,
        cache_age_seconds: int | None,
        observed_at: datetime,
    ) -> None:
        if not rows:
            return
        with self._sessions.begin() as session:
            session.add_all(
                [
                    SerpCompetitiveObservationRow(
                        rank_run_id=run_id,
                        owner_id=owner_id,
                        geo_profile_id=geo_profile_id,
                        asin=row["asin"],
                        title=row.get("title"),
                        organic_position=row.get("organic_position"),
                        sponsored_position=row.get("sponsored_position"),
                        absolute_position=row.get("absolute_position"),
                        probe_source=probe_source,
                        cache_age_seconds=cache_age_seconds,
                        observed_at=self._utc(observed_at),
                    )
                    for row in rows
                ]
            )

    def monitor_points(
        self,
        *,
        owner_id: str,
        monitor_target_id: str,
        since: datetime,
        until: datetime,
    ) -> list[dict]:
        statement = (
            select(
                SerpCompetitiveObservationRow.rank_run_id,
                SerpCompetitiveObservationRow.geo_profile_id,
                SerpCompetitiveObservationRow.asin,
                SerpCompetitiveObservationRow.title,
                SerpCompetitiveObservationRow.organic_position,
                SerpCompetitiveObservationRow.sponsored_position,
                SerpCompetitiveObservationRow.absolute_position,
                SerpCompetitiveObservationRow.probe_source,
                SerpCompetitiveObservationRow.cache_age_seconds,
                SerpCompetitiveObservationRow.observed_at,
                RankRunRow.completed_at,
            )
            .select_from(RankJobRow)
            .join(RankRunRow, RankRunRow.id == RankJobRow.run_id)
            .join(
                SerpCompetitiveObservationRow,
                and_(
                    SerpCompetitiveObservationRow.rank_run_id == RankRunRow.id,
                    SerpCompetitiveObservationRow.owner_id == owner_id,
                ),
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
                SerpCompetitiveObservationRow.geo_profile_id,
                SerpCompetitiveObservationRow.asin,
            )
        )
        with self._sessions() as session:
            rows = session.execute(statement).all()
        return [
            {
                "run_id": row.rank_run_id,
                "geo_profile_id": row.geo_profile_id,
                "asin": row.asin,
                "title": row.title,
                "organic_position": row.organic_position,
                "sponsored_position": row.sponsored_position,
                "absolute_position": row.absolute_position,
                "probe_source": row.probe_source,
                "cache_age_seconds": row.cache_age_seconds,
                "observed_at": row.observed_at,
                "completed_at": row.completed_at,
            }
            for row in rows
        ]

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
