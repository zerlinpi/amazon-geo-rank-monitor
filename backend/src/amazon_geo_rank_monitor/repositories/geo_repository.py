from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from amazon_geo_rank_monitor.domain.models import GeoProfile

from .models import GeoProfileRow


class GeoRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def create(self, *, owner_id: str, profile: GeoProfile) -> dict:
        profile_id = str(uuid4())
        with self._sessions.begin() as session:
            session.add(
                GeoProfileRow(
                    id=profile_id,
                    owner_id=owner_id,
                    name=profile.name,
                    marketplace=profile.marketplace,
                    ip_country=profile.ip_country,
                    ip_state=profile.ip_state,
                    ip_city=profile.ip_city,
                    ip_postal_code=profile.ip_postal_code,
                    delivery_country=profile.delivery_country,
                    delivery_postal_code=profile.delivery_postal_code,
                    device=profile.device,
                    weight=profile.weight,
                    enabled=profile.enabled,
                )
            )
        return self.get(profile_id, owner_id=owner_id)

    def get(self, profile_id: str, *, owner_id: str) -> dict | None:
        with self._sessions() as session:
            row = session.scalar(
                select(GeoProfileRow).where(
                    GeoProfileRow.id == profile_id,
                    GeoProfileRow.owner_id == owner_id,
                )
            )
            return self._serialize(row) if row else None

    def list(self, *, owner_id: str) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(GeoProfileRow)
                .where(GeoProfileRow.owner_id == owner_id)
                .order_by(GeoProfileRow.created_at)
            ).all()
            return [self._serialize(row) for row in rows]

    def get_domain(self, profile_id: str, *, owner_id: str) -> GeoProfile | None:
        row = self.get(profile_id, owner_id=owner_id)
        if row is None:
            return None
        return GeoProfile(
            id=row["id"],
            name=row["name"],
            marketplace=row["marketplace"],
            ip_country=row["ip_country"],
            ip_state=row["ip_state"],
            ip_city=row["ip_city"],
            ip_postal_code=row["ip_postal_code"],
            delivery_country=row["delivery_country"],
            delivery_postal_code=row["delivery_postal_code"],
            device=row["device"],
            weight=row["weight"],
            enabled=row["enabled"],
        )

    @staticmethod
    def _serialize(row: GeoProfileRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "marketplace": row.marketplace,
            "ip_country": row.ip_country,
            "ip_state": row.ip_state,
            "ip_city": row.ip_city,
            "ip_postal_code": row.ip_postal_code,
            "delivery_country": row.delivery_country,
            "delivery_postal_code": row.delivery_postal_code,
            "device": row.device,
            "weight": row.weight,
            "enabled": row.enabled,
            "created_at": row.created_at,
        }
