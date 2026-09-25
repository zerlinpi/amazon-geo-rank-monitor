from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .models import (
    SsoIdentityRow,
    SsoLoginTransactionRow,
    WorkspaceSsoConfigRow,
)


class SsoRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def get_config(self, *, owner_id: str) -> dict | None:
        with self._sessions() as session:
            row = session.get(WorkspaceSsoConfigRow, owner_id)
            return self._serialize_config(row) if row else None

    def list_enabled_configs(self) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(WorkspaceSsoConfigRow).where(
                    WorkspaceSsoConfigRow.enabled.is_(True)
                )
            ).all()
            return [self._serialize_config(row) for row in rows]

    def upsert_config(
        self,
        *,
        owner_id: str,
        provider_type: str,
        display_name: str,
        issuer_url: str,
        client_id: str,
        client_secret_encrypted: str,
        email_domains: list[str],
        auto_join: bool,
        enabled: bool,
    ) -> dict:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.get(WorkspaceSsoConfigRow, owner_id)
            if row is None:
                row = WorkspaceSsoConfigRow(
                    owner_id=owner_id,
                    provider_type=provider_type,
                    display_name=display_name,
                    issuer_url=issuer_url,
                    client_id=client_id,
                    client_secret_encrypted=client_secret_encrypted,
                    email_domains=email_domains,
                    auto_join=auto_join,
                    enabled=enabled,
                )
                session.add(row)
            else:
                changed_identity = (
                    row.issuer_url != issuer_url
                    or row.client_id != client_id
                    or row.client_secret_encrypted != client_secret_encrypted
                )
                changed_domains = row.email_domains != email_domains
                row.provider_type = provider_type
                row.display_name = display_name
                row.issuer_url = issuer_url
                row.client_id = client_id
                row.client_secret_encrypted = client_secret_encrypted
                row.email_domains = email_domains
                row.auto_join = auto_join
                row.enabled = enabled
                if changed_identity:
                    row.verified_at = None
                if changed_identity or changed_domains:
                    row.enforce_sso = False
                if not enabled:
                    row.enforce_sso = False
                row.updated_at = now
            session.flush()
            return self._serialize_config(row)

    def mark_verified(self, *, owner_id: str) -> dict:
        with self._sessions.begin() as session:
            row = session.get(WorkspaceSsoConfigRow, owner_id)
            if row is None:
                raise KeyError("SSO configuration not found")
            row.verified_at = datetime.now(UTC)
            row.updated_at = datetime.now(UTC)
            session.flush()
            return self._serialize_config(row)

    def set_enforce_sso(self, *, owner_id: str, enforce_sso: bool) -> dict:
        with self._sessions.begin() as session:
            row = session.get(WorkspaceSsoConfigRow, owner_id)
            if row is None:
                raise KeyError("SSO configuration not found")
            if enforce_sso and (not row.enabled or row.verified_at is None):
                raise ValueError("SSO must be enabled and verified before enforcement")
            row.enforce_sso = enforce_sso
            row.updated_at = datetime.now(UTC)
            session.flush()
            return self._serialize_config(row)

    def create_transaction(
        self,
        *,
        owner_id: str,
        state_hash: str,
        nonce_hash: str,
        code_verifier_encrypted: str,
        email_hint: str | None,
        expires_at: datetime,
    ) -> dict:
        row = SsoLoginTransactionRow(
            id=str(uuid4()),
            owner_id=owner_id,
            state_hash=state_hash,
            nonce_hash=nonce_hash,
            code_verifier_encrypted=code_verifier_encrypted,
            email_hint=email_hint,
            expires_at=expires_at,
        )
        with self._sessions.begin() as session:
            session.add(row)
            session.flush()
            return self._serialize_transaction(row)

    def consume_transaction(self, *, state_hash: str) -> dict:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.scalar(
                select(SsoLoginTransactionRow).where(
                    SsoLoginTransactionRow.state_hash == state_hash,
                    SsoLoginTransactionRow.used_at.is_(None),
                )
            )
            if row is None:
                raise KeyError("SSO transaction not found")
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                raise KeyError("SSO transaction not found")
            row.used_at = now
            session.flush()
            return self._serialize_transaction(row)

    def find_identity(
        self,
        *,
        owner_id: str,
        issuer: str,
        subject: str,
    ) -> dict | None:
        with self._sessions() as session:
            row = session.scalar(
                select(SsoIdentityRow).where(
                    SsoIdentityRow.owner_id == owner_id,
                    SsoIdentityRow.issuer == issuer,
                    SsoIdentityRow.subject == subject,
                )
            )
            return self._serialize_identity(row) if row else None

    def bind_identity(
        self,
        *,
        owner_id: str,
        user_id: str,
        issuer: str,
        subject: str,
        email: str,
    ) -> dict:
        try:
            with self._sessions.begin() as session:
                existing = session.scalar(
                    select(SsoIdentityRow).where(
                        SsoIdentityRow.owner_id == owner_id,
                        SsoIdentityRow.user_id == user_id,
                    )
                )
                if existing is not None:
                    if existing.issuer != issuer or existing.subject != subject:
                        raise ValueError(
                            "workspace user is already bound to another SSO identity"
                        )
                    existing.email = email
                    existing.last_login_at = datetime.now(UTC)
                    session.flush()
                    return self._serialize_identity(existing)
                row = SsoIdentityRow(
                    id=str(uuid4()),
                    owner_id=owner_id,
                    user_id=user_id,
                    issuer=issuer,
                    subject=subject,
                    email=email,
                )
                session.add(row)
                session.flush()
                return self._serialize_identity(row)
        except IntegrityError:
            raise ValueError("SSO identity is already bound") from None

    def touch_identity(self, *, identity_id: str, email: str) -> dict:
        with self._sessions.begin() as session:
            row = session.get(SsoIdentityRow, identity_id)
            if row is None:
                raise KeyError("SSO identity not found")
            row.email = email
            row.last_login_at = datetime.now(UTC)
            session.flush()
            return self._serialize_identity(row)

    @staticmethod
    def _serialize_config(row: WorkspaceSsoConfigRow) -> dict:
        return {
            "owner_id": row.owner_id,
            "provider_type": row.provider_type,
            "display_name": row.display_name,
            "issuer_url": row.issuer_url,
            "client_id": row.client_id,
            "client_secret_encrypted": row.client_secret_encrypted,
            "email_domains": list(row.email_domains or []),
            "auto_join": row.auto_join,
            "enabled": row.enabled,
            "enforce_sso": row.enforce_sso,
            "verified_at": row.verified_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _serialize_transaction(row: SsoLoginTransactionRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "state_hash": row.state_hash,
            "nonce_hash": row.nonce_hash,
            "code_verifier_encrypted": row.code_verifier_encrypted,
            "email_hint": row.email_hint,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "used_at": row.used_at,
        }

    @staticmethod
    def _serialize_identity(row: SsoIdentityRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "user_id": row.user_id,
            "issuer": row.issuer,
            "subject": row.subject,
            "email": row.email,
            "created_at": row.created_at,
            "last_login_at": row.last_login_at,
        }
