from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, and_, func, or_, select
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


    @staticmethod
    def _verification_trigger_category(trigger: str) -> str:
        for prefix in (
            "low_confidence:",
            "rank_movement:",
            "not_found_after_found:",
        ):
            if trigger.startswith(prefix):
                return prefix.removesuffix(":")
        return trigger

    def verification_analytics(
        self,
        *,
        owner_id: str,
        since: datetime,
        until: datetime,
    ) -> dict:
        totals = {
            "run_count": 0,
            "strict_requested": 0,
            "strict_attempted": 0,
            "strict_succeeded": 0,
            "strict_skipped": 0,
            "pacing_deferred": 0,
            "manual_requested": 0,
            "automatic_requested": 0,
            "unclassified_requested": 0,
            "cache_hits": 0,
            "recovered_failed_geos": 0,
        }
        trigger_counts: dict[str, int] = {}
        skip_reason_counts: dict[str, int] = {}
        daily: dict[str, dict] = {}

        with self._sessions() as session:
            rows = session.execute(
                select(
                    RankRunRow.completed_at,
                    RankRunRow.verification_metadata,
                ).where(
                    RankRunRow.owner_id == owner_id,
                    RankRunRow.completed_at.is_not(None),
                    RankRunRow.completed_at >= since,
                    RankRunRow.completed_at <= until,
                )
            ).all()

        for completed_at, metadata in rows:
            if not isinstance(metadata, dict):
                continue
            requested = int(metadata.get("strict_requested_count") or 0)
            attempted = int(metadata.get("strict_attempted_count") or 0)
            succeeded = int(metadata.get("strict_succeeded_count") or 0)
            skipped = int(metadata.get("strict_skipped_count") or 0)
            events = metadata.get("events") or []
            if not requested and not events:
                continue

            totals["run_count"] += 1
            totals["strict_requested"] += requested
            totals["strict_attempted"] += attempted
            totals["strict_succeeded"] += succeeded
            totals["strict_skipped"] += skipped

            date_key = completed_at.date().isoformat()
            point = daily.setdefault(
                date_key,
                {
                    "date": date_key,
                    "requested": 0,
                    "attempted": 0,
                    "succeeded": 0,
                    "skipped": 0,
                    "pacing_deferred": 0,
                    "manual_requested": 0,
                    "cache_hits": 0,
                    "recovered_failed_geos": 0,
                },
            )
            point["requested"] += requested
            point["attempted"] += attempted
            point["succeeded"] += succeeded
            point["skipped"] += skipped

            classified_events = 0
            for event in events:
                if not isinstance(event, dict):
                    continue
                classified_events += 1
                triggers = [
                    str(item)
                    for item in (event.get("triggers") or [])
                    if str(item)
                ]
                is_manual = "manual_force" in triggers
                if is_manual:
                    totals["manual_requested"] += 1
                    point["manual_requested"] += 1
                else:
                    totals["automatic_requested"] += 1

                if event.get("cache_hit"):
                    totals["cache_hits"] += 1
                    point["cache_hits"] += 1

                if event.get("succeeded") and "managed_probe_failed" in triggers:
                    totals["recovered_failed_geos"] += 1
                    point["recovered_failed_geos"] += 1

                for trigger in triggers:
                    category = self._verification_trigger_category(trigger)
                    trigger_counts[category] = trigger_counts.get(category, 0) + 1

                skipped_reason = event.get("skipped_reason")
                if skipped_reason:
                    key = str(skipped_reason)
                    skip_reason_counts[key] = skip_reason_counts.get(key, 0) + 1
                    if (
                        key == "daily_budget_pacing_deferred"
                        and not is_manual
                        and event.get("requested", True)
                    ):
                        totals["pacing_deferred"] += 1
                        point["pacing_deferred"] += 1

            if requested > classified_events:
                totals["unclassified_requested"] += requested - classified_events

        return {
            **totals,
            "trigger_counts": dict(sorted(trigger_counts.items())),
            "skip_reason_counts": dict(sorted(skip_reason_counts.items())),
            "daily": [daily[key] for key in sorted(daily)],
        }

    def verification_summary(
        self,
        *,
        owner_id: str | None = None,
    ) -> dict[str, int]:
        totals = {
            "strict_requested": 0,
            "strict_attempted": 0,
            "strict_succeeded": 0,
            "strict_skipped": 0,
        }
        with self._sessions() as session:
            statement = select(RankRunRow.verification_metadata)
            if owner_id is not None:
                statement = statement.where(RankRunRow.owner_id == owner_id)
            rows = session.scalars(statement).all()
        for metadata in rows:
            if not isinstance(metadata, dict):
                continue
            totals["strict_requested"] += int(
                metadata.get("strict_requested_count") or 0
            )
            totals["strict_attempted"] += int(
                metadata.get("strict_attempted_count") or 0
            )
            totals["strict_succeeded"] += int(
                metadata.get("strict_succeeded_count") or 0
            )
            totals["strict_skipped"] += int(
                metadata.get("strict_skipped_count") or 0
            )
        return totals

    def list_runs(self, *, owner_id: str, limit: int = 50) -> list[dict]:
        with self._sessions() as session:
            run_ids = session.scalars(
                select(RankRunRow.id)
                .where(RankRunRow.owner_id == owner_id)
                .order_by(RankRunRow.started_at.desc())
                .limit(limit)
            ).all()
        return [self.get_run(run_id, owner_id=owner_id) for run_id in run_ids]

    def list_run_page(
        self,
        *,
        owner_id: str,
        limit: int = 50,
        cursor: str | None = None,
        keyword: str | None = None,
        asin: str | None = None,
        status: str | None = None,
        started_from: datetime | None = None,
        started_until: datetime | None = None,
    ) -> dict:
        """Fetch bounded summaries, newest first, without loading per-run details."""
        limit = min(max(limit, 1), 100)
        statement = select(RankRunRow).where(RankRunRow.owner_id == owner_id)
        if started_from is not None:
            started_from = self._utc(started_from)
            statement = statement.where(RankRunRow.started_at >= started_from)
        if started_until is not None:
            started_until = self._utc(started_until)
            statement = statement.where(RankRunRow.started_at <= started_until)
        if (
            started_from is not None
            and started_until is not None
            and started_from > started_until
        ):
            raise ValueError("started_from must be before or equal to started_until")
        if keyword and keyword.strip():
            statement = statement.where(
                RankRunRow.keyword.icontains(keyword.strip(), autoescape=True)
            )
        if status:
            statement = statement.where(RankRunRow.status == status)
        if asin and asin.strip():
            normalized_asin = asin.strip().upper()
            statement = statement.where(or_(
                select(RankSnapshotRow.id).where(
                    RankSnapshotRow.rank_run_id == RankRunRow.id,
                    RankSnapshotRow.asin == normalized_asin,
                ).exists(),
                select(RankObservationRow.id).where(
                    RankObservationRow.rank_run_id == RankRunRow.id,
                    RankObservationRow.asin == normalized_asin,
                ).exists(),
            ))

        with self._sessions() as session:
            if cursor:
                anchor = session.execute(
                    select(RankRunRow.started_at, RankRunRow.id).where(
                        RankRunRow.id == cursor,
                        RankRunRow.owner_id == owner_id,
                    )
                ).one_or_none()
                if anchor is None:
                    raise ValueError("invalid run history cursor")
                statement = statement.where(or_(
                    RankRunRow.started_at < anchor.started_at,
                    and_(
                        RankRunRow.started_at == anchor.started_at,
                        RankRunRow.id < anchor.id,
                    ),
                ))

            runs = session.scalars(statement.order_by(
                RankRunRow.started_at.desc(), RankRunRow.id.desc(),
            ).limit(limit + 1)).all()
            has_more = len(runs) > limit
            runs = runs[:limit]
            if not runs:
                return {"items": [], "next_cursor": None}
            snapshot_counts = dict(session.execute(
                select(RankSnapshotRow.rank_run_id, func.count(RankSnapshotRow.id))
                .where(RankSnapshotRow.rank_run_id.in_([run.id for run in runs]))
                .group_by(RankSnapshotRow.rank_run_id)
            ).all())
            # Full verification events and budget evidence belong to the detail view.
            summary_keys = (
                "auto_strict_enabled", "manual_force_requested",
                "strict_requested_count", "strict_attempted_count",
                "strict_succeeded_count", "strict_skipped_count",
            )
            return {
                "items": [
                    {
                        "id": run.id,
                        "marketplace": run.marketplace,
                        "keyword": run.keyword,
                        "status": run.status,
                        "requested_probe_count": run.requested_probe_count,
                        "settled_probe_count": run.settled_probe_count,
                        "cache_hit_count": run.cache_hit_count,
                        "snapshot_count": snapshot_counts.get(run.id, 0),
                        "started_at": self._utc(run.started_at),
                        "completed_at": (
                            self._utc(run.completed_at) if run.completed_at else None
                        ),
                        "verification_metadata": {
                            key: value
                            for key, value in (run.verification_metadata or {}).items()
                            if key in summary_keys
                        },
                    }
                    for run in runs
                ],
                "next_cursor": runs[-1].id if has_more else None,
            }

    @staticmethod
    def _utc(value: datetime) -> datetime:
        # SQLite drops timezone info from UTC values stored by the application.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        try:
            return value.astimezone(UTC)
        except OverflowError as exc:
            raise ValueError("timestamp is outside the supported UTC range") from exc
