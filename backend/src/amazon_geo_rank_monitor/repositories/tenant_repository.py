from __future__ import annotations

from datetime import UTC, datetime
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

    def create_api_key(
        self,
        *,
        owner_id: str,
        name: str,
        prefix: str,
        key_hash: str,
    ) -> dict:
        key_id = str(uuid4())
        with self._sessions.begin() as session:
            row = ApiKeyRow(
                id=key_id,
                owner_id=owner_id,
                name=name.strip(),
                prefix=prefix,
                key_hash=key_hash,
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

    def touch_api_key(self, key_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(ApiKeyRow, key_id)
            if row is not None:
                row.last_used_at = datetime.now(UTC)

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
    def _serialize_key(row: ApiKeyRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "prefix": row.prefix,
            "key_hash": row.key_hash,
            "created_at": row.created_at,
            "last_used_at": row.last_used_at,
            "revoked_at": row.revoked_at,
        }
