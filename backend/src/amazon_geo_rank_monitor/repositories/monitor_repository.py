from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

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
        schedule: str | None = None,
    ) -> dict:
        if provider_mode not in {"managed", "strict"}:
            raise ValueError("provider_mode must be managed or strict")
        normalized_asins = list(\n            dict.fromkeys(asin.strip().upper() for asin in asins if asin.strip())\n        )
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
                    schedule=schedule,
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

    def list(self, *, owner_id: str) -> list[dict]:
        with self._sessions() as session:
            ids = session.scalars(
                select(MonitorTargetRow.id)
                .where(MonitorTargetRow.owner_id == owner_id)
                .order_by(MonitorTargetRow.created_at)
            ).all()
        return [item for item in (self.get(i, owner_id=owner_id) for i in ids) if item]

    @staticmethod
    def _serialize(row: MonitorTargetRow, asins: list[str], geo_ids: list[str]) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "marketplace": row.marketplace,
            "keyword": row.keyword,
            "search_depth": row.search_depth,
            "provider_mode": row.provider_mode,
            "schedule": row.schedule,
            "enabled": row.enabled,
            "asins": asins,
            "geo_profile_ids": geo_ids,
            "created_at": row.created_at,
        }
