from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import sessionmaker

from amazon_geo_rank_monitor.scheduling.cron import normalize_schedule

from .models import (
    GeoProfileRow,
    MonitorTargetAsinRow,
    MonitorTargetGeoRow,
    MonitorTargetRow,
)


class MonitorRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def create(
        self,
        *,
        owner_id: str,
        name: str,
        marketplace: str,
        keyword: str,
        asins: list[str],
        geo_profile_ids: list[str],
        search_depth: int,
        provider_mode: str,
        auto_strict_enabled: bool | None = None,
        auto_strict_min_confidence: Decimal | float | str | None = None,
        auto_strict_max_probes_per_run: int | None = None,
        schedule: str | None = None,
    ) -> dict:
        if provider_mode not in {"managed", "strict"}:
            raise ValueError("provider_mode must be managed or strict")
        confidence = (
            None
            if auto_strict_min_confidence is None
            else Decimal(str(auto_strict_min_confidence))
        )
        if confidence is not None and (confidence <= 0 or confidence > 1):
            raise ValueError(
                "auto_strict_min_confidence must be greater than 0 and at most 1"
            )
        if (
            auto_strict_max_probes_per_run is not None
            and auto_strict_max_probes_per_run < 0
        ):
            raise ValueError(
                "auto_strict_max_probes_per_run must be non-negative"
            )
        normalized_schedule = normalize_schedule(schedule)
        normalized_asins = list(
            dict.fromkeys(asin.strip().upper() for asin in asins if asin.strip())
        )
        if not normalized_asins:
            raise ValueError("at least one ASIN is required")
        if not geo_profile_ids:
            raise ValueError("at least one geo profile is required")

        with self._sessions.begin() as session:
            owned_geo_ids = set(
                session.scalars(
                    select(GeoProfileRow.id).where(
                        GeoProfileRow.owner_id == owner_id,
                        GeoProfileRow.id.in_(geo_profile_ids),
                    )
                ).all()
            )
            if owned_geo_ids != set(geo_profile_ids):
                raise KeyError("one or more geo profiles are not available to this tenant")

            monitor_id = str(uuid4())
            session.add(
                MonitorTargetRow(
                    id=monitor_id,
                    owner_id=owner_id,
                    name=name.strip(),
                    marketplace=marketplace.strip(),
                    keyword=keyword.strip(),
                    search_depth=search_depth,
                    provider_mode=provider_mode,
                    auto_strict_enabled=auto_strict_enabled,
                    auto_strict_min_confidence=confidence,
                    auto_strict_max_probes_per_run=(
                        auto_strict_max_probes_per_run
                    ),
                    schedule=normalized_schedule,
                )
            )
            session.add_all(
                [
                    MonitorTargetAsinRow(
                        monitor_target_id=monitor_id,
                        asin=asin,
                    )
                    for asin in normalized_asins
                ]
            )
            session.add_all(
                [
                    MonitorTargetGeoRow(
                        monitor_target_id=monitor_id,
                        geo_profile_id=geo_id,
                    )
                    for geo_id in dict.fromkeys(geo_profile_ids)
                ]
            )
        return self.get(monitor_id, owner_id=owner_id)

    def get(self, monitor_id: str, *, owner_id: str) -> dict | None:
        with self._sessions() as session:
            row = session.scalar(
                select(MonitorTargetRow).where(
                    MonitorTargetRow.id == monitor_id,
                    MonitorTargetRow.owner_id == owner_id,
                )
            )
            if row is None:
                return None
            asins = session.scalars(
                select(MonitorTargetAsinRow.asin)
                .where(MonitorTargetAsinRow.monitor_target_id == monitor_id)
                .order_by(MonitorTargetAsinRow.id)
            ).all()
            geo_ids = session.scalars(
                select(MonitorTargetGeoRow.geo_profile_id)
                .where(MonitorTargetGeoRow.monitor_target_id == monitor_id)
                .order_by(MonitorTargetGeoRow.id)
            ).all()
            return self._serialize(row, list(asins), list(geo_ids))

    def update(
        self,
        monitor_id: str,
        *,
        owner_id: str,
        changes: dict,
    ) -> dict:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(MonitorTargetRow).where(
                    MonitorTargetRow.id == monitor_id,
                    MonitorTargetRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise KeyError(f"monitor not found: {monitor_id}")

            if "provider_mode" in changes:
                provider_mode = changes["provider_mode"]
                if provider_mode not in {"managed", "strict"}:
                    raise ValueError("provider_mode must be managed or strict")
                row.provider_mode = provider_mode

            for field in ("name", "marketplace", "keyword"):
                if field in changes:
                    value = changes[field]
                    if value is None or not value.strip():
                        raise ValueError(f"{field} must not be empty")
                    setattr(row, field, value.strip())

            if "search_depth" in changes:
                value = changes["search_depth"]
                if value is None or value < 1:
                    raise ValueError("search_depth must be positive")
                row.search_depth = value

            if "auto_strict_enabled" in changes:
                row.auto_strict_enabled = changes["auto_strict_enabled"]

            if "auto_strict_min_confidence" in changes:
                value = changes["auto_strict_min_confidence"]
                if value is None:
                    row.auto_strict_min_confidence = None
                else:
                    confidence = Decimal(str(value))
                    if confidence <= 0 or confidence > 1:
                        raise ValueError(
                            "auto_strict_min_confidence must be greater than 0 "
                            "and at most 1"
                        )
                    row.auto_strict_min_confidence = confidence

            if "auto_strict_max_probes_per_run" in changes:
                value = changes["auto_strict_max_probes_per_run"]
                if value is not None and value < 0:
                    raise ValueError(
                        "auto_strict_max_probes_per_run must be non-negative"
                    )
                row.auto_strict_max_probes_per_run = value

            if "schedule" in changes:
                row.schedule = normalize_schedule(changes["schedule"])

            if "enabled" in changes:
                if changes["enabled"] is None:
                    raise ValueError("enabled must be true or false")
                row.enabled = changes["enabled"]

            if "asins" in changes:
                normalized_asins = list(
                    dict.fromkeys(
                        asin.strip().upper()
                        for asin in changes["asins"] or []
                        if asin.strip()
                    )
                )
                if not normalized_asins:
                    raise ValueError("at least one ASIN is required")
                session.execute(
                    delete(MonitorTargetAsinRow).where(
                        MonitorTargetAsinRow.monitor_target_id == monitor_id
                    )
                )
                session.add_all(
                    [
                        MonitorTargetAsinRow(
                            monitor_target_id=monitor_id,
                            asin=asin,
                        )
                        for asin in normalized_asins
                    ]
                )

            if "geo_profile_ids" in changes:
                geo_profile_ids = list(dict.fromkeys(changes["geo_profile_ids"] or []))
                if not geo_profile_ids:
                    raise ValueError("at least one geo profile is required")
                owned_geo_ids = set(
                    session.scalars(
                        select(GeoProfileRow.id).where(
                            GeoProfileRow.owner_id == owner_id,
                            GeoProfileRow.id.in_(geo_profile_ids),
                        )
                    ).all()
                )
                if owned_geo_ids != set(geo_profile_ids):
                    raise KeyError("one or more geo profiles are not available to this tenant")
                session.execute(
                    delete(MonitorTargetGeoRow).where(
                        MonitorTargetGeoRow.monitor_target_id == monitor_id
                    )
                )
                session.add_all(
                    [
                        MonitorTargetGeoRow(
                            monitor_target_id=monitor_id,
                            geo_profile_id=geo_id,
                        )
                        for geo_id in geo_profile_ids
                    ]
                )

        updated = self.get(monitor_id, owner_id=owner_id)
        if updated is None:
            raise KeyError(f"monitor not found: {monitor_id}")
        return updated

    def delete(self, monitor_id: str, *, owner_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(MonitorTargetRow).where(
                    MonitorTargetRow.id == monitor_id,
                    MonitorTargetRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise KeyError(f"monitor not found: {monitor_id}")
            session.execute(
                delete(MonitorTargetAsinRow).where(
                    MonitorTargetAsinRow.monitor_target_id == monitor_id
                )
            )
            session.execute(
                delete(MonitorTargetGeoRow).where(
                    MonitorTargetGeoRow.monitor_target_id == monitor_id
                )
            )
            session.delete(row)

    def list(self, *, owner_id: str) -> list[dict]:
        with self._sessions() as session:
            ids = session.scalars(
                select(MonitorTargetRow.id)
                .where(MonitorTargetRow.owner_id == owner_id)
                .order_by(MonitorTargetRow.created_at)
            ).all()
        return [item for item in (self.get(i, owner_id=owner_id) for i in ids) if item]

    def list_scheduled(self) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(MonitorTargetRow)
                .where(
                    MonitorTargetRow.enabled.is_(True),
                    MonitorTargetRow.schedule.is_not(None),
                )
                .order_by(MonitorTargetRow.created_at, MonitorTargetRow.id)
            ).all()
            pairs = [
                (row.id, row.owner_id)
                for row in rows
                if row.schedule and row.schedule.strip()
            ]
        return [
            item
            for monitor_id, owner_id in pairs
            if (item := self.get(monitor_id, owner_id=owner_id)) is not None
        ]

    @staticmethod
    def _serialize(
        row: MonitorTargetRow,
        asins: list[str],
        geo_ids: list[str],
    ) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "marketplace": row.marketplace,
            "keyword": row.keyword,
            "search_depth": row.search_depth,
            "provider_mode": row.provider_mode,
            "auto_strict_enabled": row.auto_strict_enabled,
            "auto_strict_min_confidence": row.auto_strict_min_confidence,
            "auto_strict_max_probes_per_run": (
                row.auto_strict_max_probes_per_run
            ),
            "schedule": row.schedule,
            "enabled": row.enabled,
            "asins": asins,
            "geo_profile_ids": geo_ids,
            "created_at": row.created_at,
        }
