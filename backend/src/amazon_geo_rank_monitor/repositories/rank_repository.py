from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from amazon_geo_rank_monitor.domain.models import RankObservation, RankSnapshot
from amazon_geo_rank_monitor.repositories.models import (
    RankObservationRow,
    RankRunRow,
    RankSnapshotRow,
)


class RankRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def create_run(
        self,
        *,
        marketplace: str,
        keyword: str,
        requested_probe_count: int,
        owner_id: str | None = None,
    ) -> str:
        run_id = str(uuid4())
        with self._sessions.begin() as session:
            session.add(
                RankRunRow(
                    id=run_id,
                    owner_id=owner_id,
                    marketplace=marketplace,
                    keyword=keyword,
                    status="running",
                    requested_probe_count=requested_probe_count,
                    settled_probe_count=0,
                )
            )
        return run_id

    def save_observations(
        self, run_id: str, observations: list[RankObservation]
    ) -> None:
        with self._sessions.begin() as session:
            for observation in observations:
                session.add(
                    RankObservationRow(
                        rank_run_id=run_id,
                        asin=observation.asin,
                        geo_profile_id=observation.geo_profile_id,
                        provider=observation.provider,
                        verification_level=observation.verification_level.value,
                        status=observation.status.value,
                        found=observation.found,
                        organic_rank=observation.organic_rank,
                        absolute_rank=observation.absolute_rank,
                        sponsored_rank=observation.sponsored_rank,
                        effective_rank=observation.effective_rank,
                        page=observation.page,
                        observed_at=observation.observed_at,
                        raw_result_reference=observation.raw_result_reference,
                        probe_source=observation.probe_source,
                        cache_age_seconds=observation.cache_age_seconds,
                    )
                )

    def save_snapshots(self, run_id: str, snapshots: list[RankSnapshot]) -> None:
        with self._sessions.begin() as session:
            for snapshot in snapshots:
                session.add(
                    RankSnapshotRow(
                        rank_run_id=run_id,
                        asin=snapshot.asin,
                        weighted_rank=snapshot.weighted_rank,
                        found_weight=snapshot.found_weight,
                        missing_weight=snapshot.missing_weight,
                        confidence=snapshot.confidence,
                        created_at=snapshot.created_at,
                    )
                )

    def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        settled_probe_count: int,
        cache_hit_count: int = 0,
        verification_metadata: dict | None = None,
        error_summary: str | None = None,
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(RankRunRow, run_id)
            if row is None:
                raise KeyError(f"rank run not found: {run_id}")
            row.status = status
            row.settled_probe_count = settled_probe_count
            row.cache_hit_count = cache_hit_count
            row.verification_metadata = verification_metadata or {}
            row.error_summary = error_summary
            row.completed_at = datetime.now(UTC)

    def get_run(self, run_id: str, *, owner_id: str | None = None) -> dict:
        with self._sessions() as session:
            statement = select(RankRunRow).where(RankRunRow.id == run_id)
            if owner_id is not None:
                statement = statement.where(RankRunRow.owner_id == owner_id)
            run = session.scalar(statement)
            if run is None:
                raise KeyError(f"rank run not found: {run_id}")
            return self._serialize_run(session, run)

    def previous_observations(
        self,
        *,
        owner_id: str | None,
        marketplace: str,
        keyword: str,
        geo_profile_id: str,
        exclude_run_id: str,
    ) -> list[RankObservation]:
        with self._sessions() as session:
            statement = (
                select(RankRunRow)
                .where(
                    RankRunRow.marketplace == marketplace,
                    RankRunRow.keyword == keyword,
                    RankRunRow.id != exclude_run_id,
                    RankRunRow.status.in_(("succeeded", "partially_succeeded")),
                )
                .order_by(
                    RankRunRow.completed_at.desc(),
                    RankRunRow.started_at.desc(),
                )
                .limit(1)
            )
            if owner_id is None:
                statement = statement.where(RankRunRow.owner_id.is_(None))
            else:
                statement = statement.where(RankRunRow.owner_id == owner_id)
            previous_run = session.scalar(statement)
            if previous_run is None:
                return []

            rows = session.scalars(
                select(RankObservationRow)
                .where(
                    RankObservationRow.rank_run_id == previous_run.id,
                    RankObservationRow.geo_profile_id == geo_profile_id,
                )
                .order_by(RankObservationRow.id)
            ).all()

            preferred: dict[str, RankObservationRow] = {}
            for row in rows:
                current = preferred.get(row.asin)
                if current is None or (
                    row.verification_level == "strict"
                    and current.verification_level != "strict"
                ):
                    preferred[row.asin] = row

            return [
                RankObservation(
                    asin=row.asin,
                    geo_profile_id=row.geo_profile_id,
                    provider=row.provider,
                    verification_level=row.verification_level,
                    status=row.status,
                    found=row.found,
                    organic_rank=row.organic_rank,
                    absolute_rank=row.absolute_rank,
                    sponsored_rank=row.sponsored_rank,
                    effective_rank=row.effective_rank,
                    page=row.page,
                    observed_at=row.observed_at,
                    raw_result_reference=row.raw_result_reference,
                    probe_source=row.probe_source,
                    cache_age_seconds=row.cache_age_seconds,
                )
                for row in preferred.values()
            ]

    @staticmethod
    def _serialize_run(session: Session, run: RankRunRow) -> dict:
        observations = session.scalars(
            select(RankObservationRow)
            .where(RankObservationRow.rank_run_id == run.id)
            .order_by(RankObservationRow.id)
        ).all()
        snapshots = session.scalars(
            select(RankSnapshotRow)
            .where(RankSnapshotRow.rank_run_id == run.id)
            .order_by(RankSnapshotRow.id)
        ).all()
        return {
            "id": run.id,
            "owner_id": run.owner_id,
            "marketplace": run.marketplace,
            "keyword": run.keyword,
            "status": run.status,
            "requested_probe_count": run.requested_probe_count,
            "settled_probe_count": run.settled_probe_count,
            "cache_hit_count": run.cache_hit_count,
            "verification_metadata": run.verification_metadata or {},
            "error_summary": run.error_summary,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "observations": [
                {
                    "asin": row.asin,
                    "geo_profile_id": row.geo_profile_id,
                    "provider": row.provider,
                    "verification_level": row.verification_level,
                    "status": row.status,
                    "found": row.found,
                    "organic_rank": row.organic_rank,
                    "absolute_rank": row.absolute_rank,
                    "sponsored_rank": row.sponsored_rank,
                    "effective_rank": row.effective_rank,
                    "page": row.page,
                    "observed_at": row.observed_at,
                    "raw_result_reference": row.raw_result_reference,
                    "probe_source": row.probe_source,
                    "cache_age_seconds": row.cache_age_seconds,
                }
                for row in observations
            ],
            "snapshots": [
                {
                    "asin": row.asin,
                    "weighted_rank": row.weighted_rank,
                    "found_weight": row.found_weight,
                    "missing_weight": row.missing_weight,
                    "confidence": row.confidence,
                    "created_at": row.created_at,
                }
                for row in snapshots
            ],
        }


    def list_runs(self, *, owner_id: str, limit: int = 50) -> list[dict]:
        with self._sessions() as session:
            run_ids = session.scalars(
                select(RankRunRow.id)
                .where(RankRunRow.owner_id == owner_id)
                .order_by(RankRunRow.started_at.desc())
                .limit(limit)
            ).all()
        return [self.get_run(run_id, owner_id=owner_id) for run_id in run_ids]
