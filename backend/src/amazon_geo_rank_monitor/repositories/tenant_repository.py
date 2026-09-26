from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from .models import ApiKeyRow, TenantRow


class TenantRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def create_tenant(self, name: str) -> dict:
        tenant_id = str(uuid4())
        with self._sessions.begin() as session:
            row = TenantRow(id=tenant_id, name=name.strip())
            session.add(row)
        return {"id": tenant_id, "name": name.strip()}

    def get_workspace_verification_policy(self, *, owner_id: str) -> dict:
        with self._sessions() as session:
            row = session.get(TenantRow, owner_id)
            if row is None:
                raise KeyError(f"tenant not found: {owner_id}")
            return self._serialize_verification_policy(row)

    def update_workspace_verification_policy(
        self,
        *,
        owner_id: str,
        changes: dict,
    ) -> dict:
        with self._sessions.begin() as session:
            row = session.get(TenantRow, owner_id)
            if row is None:
                raise KeyError(f"tenant not found: {owner_id}")

            if "enabled" in changes:
                row.auto_strict_enabled = changes["enabled"]

            if "min_confidence" in changes:
                value = changes["min_confidence"]
                if value is None:
                    row.auto_strict_min_confidence = None
                else:
                    confidence = Decimal(str(value))
                    if confidence <= 0 or confidence > 1:
                        raise ValueError(
                            "min_confidence must be greater than 0 and at most 1"
                        )
                    row.auto_strict_min_confidence = confidence

            if "max_upstream_probes_per_run" in changes:
                value = changes["max_upstream_probes_per_run"]
                if value is not None and (value < 0 or value > 100):
                    raise ValueError(
                        "max_upstream_probes_per_run must be between 0 and 100"
                    )
                row.auto_strict_max_probes_per_run = value

            session.flush()
            return self._serialize_verification_policy(row)

    def create_api_key(
        self,
        *,
        owner_id: str,
        name: str,
        prefix: str,
        key_hash: str,
        scopes: list[str],
    ) -> dict:
        key_id = str(uuid4())
        with self._sessions.begin() as session:
            row = ApiKeyRow(
                id=key_id,
                owner_id=owner_id,
                name=name.strip(),
                prefix=prefix,
                key_hash=key_hash,
                scopes=scopes,
            )
            session.add(row)
        return self.get_api_key(key_id, owner_id=owner_id)

    def get_api_key(self, key_id: str, *, owner_id: str) -> dict:
        with self._sessions() as session:
            row = session.scalar(
                select(ApiKeyRow).where(
                    ApiKeyRow.id == key_id,
                    ApiKeyRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise KeyError(f"API key not found: {key_id}")
            return self._serialize_key(row)

    def list_api_keys(self, *, owner_id: str) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ApiKeyRow)
                .where(ApiKeyRow.owner_id == owner_id)
                .order_by(ApiKeyRow.created_at)
            ).all()
            return [self._serialize_key(row) for row in rows]

    def find_active_api_key_by_prefix(self, prefix: str) -> dict | None:
        with self._sessions() as session:
            row = session.scalar(
                select(ApiKeyRow).where(
                    ApiKeyRow.prefix == prefix,
                    ApiKeyRow.revoked_at.is_(None),
                )
            )
            return self._serialize_key(row) if row else None

    def touch_api_key(self, key_id: str, *, client_ip: str | None = None) -> None:
        with self._sessions.begin() as session:
            row = session.get(ApiKeyRow, key_id)
            if row is not None:
                row.last_used_at = datetime.now(UTC)
                row.last_used_ip = client_ip
                row.usage_count += 1

    def revoke_api_key(self, key_id: str, *, owner_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(ApiKeyRow).where(
                    ApiKeyRow.id == key_id,
                    ApiKeyRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise KeyError(f"API key not found: {key_id}")
            row.revoked_at = datetime.now(UTC)

    @staticmethod
    def _serialize_verification_policy(row: TenantRow) -> dict:
        return {
            "owner_id": row.id,
            "enabled": row.auto_strict_enabled,
            "min_confidence": row.auto_strict_min_confidence,
            "max_upstream_probes_per_run": (
                row.auto_strict_max_probes_per_run
            ),
        }

    @staticmethod
    def _serialize_key(row: ApiKeyRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "prefix": row.prefix,
            "key_hash": row.key_hash,
            "scopes": list(row.scopes or ["*"]),
            "created_at": row.created_at,
            "last_used_at": row.last_used_at,
            "last_used_ip": row.last_used_ip,
            "usage_count": row.usage_count,
            "revoked_at": row.revoked_at,
        }
