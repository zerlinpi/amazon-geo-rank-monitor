from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from .models import AuditEventRow


class AuditRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def record(
        self,
        *,
        owner_id: str,
        api_key_id: str | None,
        request_id: str,
        method: str,
        path: str,
        status_code: int,
        client_ip: str | None,
        user_agent: str | None,
    ) -> dict:
        row = AuditEventRow(
            id=str(uuid4()),
            owner_id=owner_id,
            api_key_id=api_key_id,
            request_id=request_id,
            method=method[:16],
            path=path[:512],
            status_code=status_code,
            client_ip=client_ip[:64] if client_ip else None,
            user_agent=user_agent[:512] if user_agent else None,
            created_at=datetime.now(UTC),
        )
        with self._sessions.begin() as session:
            session.add(row)
        return self._serialize(row)

    def list(
        self,
        *,
        owner_id: str,
        limit: int = 100,
        api_key_id: str | None = None,
    ) -> list[dict]:
        statement = select(AuditEventRow).where(AuditEventRow.owner_id == owner_id)
        if api_key_id:
            statement = statement.where(AuditEventRow.api_key_id == api_key_id)
        statement = statement.order_by(
            AuditEventRow.created_at.desc(),
            AuditEventRow.id.desc(),
        ).limit(min(max(limit, 1), 500))
        with self._sessions() as session:
            rows = session.scalars(statement).all()
            return [self._serialize(row) for row in rows]

    @staticmethod
    def _serialize(row: AuditEventRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "api_key_id": row.api_key_id,
            "request_id": row.request_id,
            "method": row.method,
            "path": row.path,
            "status_code": row.status_code,
            "client_ip": row.client_ip,
            "user_agent": row.user_agent,
            "created_at": row.created_at,
        }
