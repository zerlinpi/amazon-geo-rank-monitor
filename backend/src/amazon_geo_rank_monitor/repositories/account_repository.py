from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .models import (
    AccountTokenRow,
    AuthEventRow,
    MfaRecoveryCodeRow,
    TenantRow,
    TrustedDeviceRow,
    UserRow,
    UserSessionRow,
    WorkspaceInvitationRow,
    WorkspaceMembershipRow,
    WorkspaceSsoConfigRow,
)


class AccountRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def create_workspace_owner(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        workspace_name: str,
    ) -> tuple[dict, dict]:
        user_id = str(uuid4())
        owner_id = str(uuid4())
        membership_id = str(uuid4())
        try:
            with self._sessions.begin() as session:
                session.add(
                    UserRow(
                        id=user_id,
                        email=email,
                        password_hash=password_hash,
                        display_name=display_name,
                    )
                )
                session.add(TenantRow(id=owner_id, name=workspace_name))
                session.add(
                    WorkspaceMembershipRow(
                        id=membership_id,
                        owner_id=owner_id,
                        user_id=user_id,
                        role="owner",
                    )
                )
        except IntegrityError:
            raise ValueError("an account with this email already exists") from None
        return self.get_user(user_id), self.get_membership(
            user_id=user_id,
            owner_id=owner_id,
        )

    def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
    ) -> dict:
        user_id = str(uuid4())
        try:
            with self._sessions.begin() as session:
                session.add(
                    UserRow(
                        id=user_id,
                        email=email,
                        password_hash=password_hash,
                        display_name=display_name,
                    )
                )
        except IntegrityError:
            raise ValueError("an account with this email already exists") from None
        return self.get_user(user_id)

    def create_membership(
        self,
        *,
        owner_id: str,
        user_id: str,
        role: str = "viewer",
    ) -> dict:
        with self._sessions.begin() as session:
            tenant = session.get(TenantRow, owner_id)
            user = session.get(UserRow, user_id)
            if tenant is None:
                raise KeyError("workspace not found")
            if user is None:
                raise KeyError("user not found")
            existing = session.scalar(
                select(WorkspaceMembershipRow).where(
                    WorkspaceMembershipRow.owner_id == owner_id,
                    WorkspaceMembershipRow.user_id == user_id,
                )
            )
            if existing is not None:
                if existing.suspended_at is not None:
                    raise PermissionError("workspace membership is suspended")
                return self._serialize_membership(existing)
            row = WorkspaceMembershipRow(
                id=str(uuid4()),
                owner_id=owner_id,
                user_id=user_id,
                role=role,
            )
            session.add(row)
            session.flush()
            return self._serialize_membership(row)

    def create_owner_membership(
        self,
        *,
        owner_id: str,
        user_id: str,
    ) -> dict:
        with self._sessions.begin() as session:
            tenant = session.get(TenantRow, owner_id)
            if tenant is None:
                raise KeyError("workspace not found")
            existing = session.scalar(
                select(WorkspaceMembershipRow).where(
                    WorkspaceMembershipRow.owner_id == owner_id,
                    WorkspaceMembershipRow.user_id == user_id,
                )
            )
            if existing is not None:
                return self._serialize_membership(existing)
            row = WorkspaceMembershipRow(
                id=str(uuid4()),
                owner_id=owner_id,
                user_id=user_id,
                role="owner",
            )
            session.add(row)
            session.flush()
            return self._serialize_membership(row)

    def get_user(self, user_id: str) -> dict:
        with self._sessions() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError("user not found")
            return self._serialize_user(row)

    def find_user_by_email(self, email: str) -> dict | None:
        with self._sessions() as session:
            row = session.scalar(select(UserRow).where(UserRow.email == email))
            return self._serialize_user(row) if row else None

    def list_memberships(self, *, user_id: str) -> list[dict]:
        with self._sessions() as session:
            rows = session.execute(
                select(WorkspaceMembershipRow, TenantRow)
                .join(TenantRow, TenantRow.id == WorkspaceMembershipRow.owner_id)
                .where(
                    WorkspaceMembershipRow.user_id == user_id,
                    WorkspaceMembershipRow.suspended_at.is_(None),
                )
                .order_by(WorkspaceMembershipRow.created_at)
            ).all()
            return [
                {
                    **self._serialize_membership(membership),
                    "workspace_name": tenant.name,
                    "require_mfa": tenant.require_mfa,
                }
                for membership, tenant in rows
            ]

    def get_membership(
        self,
        *,
        user_id: str,
        owner_id: str,
        include_suspended: bool = False,
    ) -> dict:
        with self._sessions() as session:
            conditions = [
                WorkspaceMembershipRow.user_id == user_id,
                WorkspaceMembershipRow.owner_id == owner_id,
            ]
            if not include_suspended:
                conditions.append(WorkspaceMembershipRow.suspended_at.is_(None))
            row = session.scalar(
                select(WorkspaceMembershipRow).where(*conditions)
            )
            if row is None:
                raise KeyError("workspace membership not found")
            return self._serialize_membership(row)

    def list_members(self, *, owner_id: str) -> list[dict]:
        with self._sessions() as session:
            rows = session.execute(
                select(WorkspaceMembershipRow, UserRow)
                .join(UserRow, UserRow.id == WorkspaceMembershipRow.user_id)
                .where(WorkspaceMembershipRow.owner_id == owner_id)
                .order_by(WorkspaceMembershipRow.created_at, UserRow.email)
            ).all()
            return [
                {
                    **self._serialize_membership(membership),
                    "email": user.email,
                    "display_name": user.display_name,
                    "disabled_at": user.disabled_at,
                    "mfa_enabled": user.mfa_enabled_at is not None,
                }
                for membership, user in rows
            ]

    def update_member_role(
        self,
        *,
        owner_id: str,
        user_id: str,
        role: str,
    ) -> dict:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(WorkspaceMembershipRow).where(
                    WorkspaceMembershipRow.owner_id == owner_id,
                    WorkspaceMembershipRow.user_id == user_id,
                )
            )
            if row is None:
                raise KeyError("workspace membership not found")
            if row.role == "owner" and role != "owner":
                owner_count = session.scalar(
                    select(func.count(WorkspaceMembershipRow.id)).where(
                        WorkspaceMembershipRow.owner_id == owner_id,
                        WorkspaceMembershipRow.role == "owner",
                    )
                )
                if int(owner_count or 0) <= 1:
                    raise ValueError("workspace must keep at least one owner")
            row.role = role
            session.flush()
            return self._serialize_membership(row)

    def remove_member(self, *, owner_id: str, user_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(WorkspaceMembershipRow).where(
                    WorkspaceMembershipRow.owner_id == owner_id,
                    WorkspaceMembershipRow.user_id == user_id,
                )
            )
            if row is None:
                raise KeyError("workspace membership not found")
            if row.role == "owner":
                owner_count = session.scalar(
                    select(func.count(WorkspaceMembershipRow.id)).where(
                        WorkspaceMembershipRow.owner_id == owner_id,
                        WorkspaceMembershipRow.role == "owner",
                    )
                )
                if int(owner_count or 0) <= 1:
                    raise ValueError("workspace must keep at least one owner")
            session.delete(row)

    def create_session(
        self,
        *,
        user_id: str,
        owner_id: str,
        token_hash: str,
        csrf_hash: str,
        expires_at: datetime,
        client_ip: str | None = None,
        user_agent: str | None = None,
        mfa_authenticated: bool = False,
        auth_method: str = "local",
        sso_owner_id: str | None = None,
    ) -> dict:
        session_id = str(uuid4())
        with self._sessions.begin() as session:
            row = UserSessionRow(
                id=session_id,
                user_id=user_id,
                owner_id=owner_id,
                token_hash=token_hash,
                csrf_hash=csrf_hash,
                created_ip=client_ip[:64] if client_ip else None,
                last_seen_ip=client_ip[:64] if client_ip else None,
                user_agent=user_agent[:512] if user_agent else None,
                expires_at=expires_at,
                mfa_authenticated_at=(
                    datetime.now(UTC) if mfa_authenticated else None
                ),
                auth_method=auth_method,
                sso_owner_id=sso_owner_id,
            )
            session.add(row)
        return self.get_session_by_hash(token_hash)

    def get_session_by_hash(self, token_hash: str) -> dict:
        now = datetime.now(UTC)
        with self._sessions() as session:
            result = session.execute(
                select(
                    UserSessionRow,
                    UserRow,
                    WorkspaceMembershipRow,
                    TenantRow,
                    WorkspaceSsoConfigRow,
                )
                .join(UserRow, UserRow.id == UserSessionRow.user_id)
                .join(
                    WorkspaceMembershipRow,
                    (WorkspaceMembershipRow.user_id == UserSessionRow.user_id)
                    & (WorkspaceMembershipRow.owner_id == UserSessionRow.owner_id),
                )
                .join(TenantRow, TenantRow.id == UserSessionRow.owner_id)
                .outerjoin(
                    WorkspaceSsoConfigRow,
                    WorkspaceSsoConfigRow.owner_id == UserSessionRow.owner_id,
                )
                .where(
                    UserSessionRow.token_hash == token_hash,
                    UserSessionRow.revoked_at.is_(None),
                    UserSessionRow.expires_at > now,
                    UserRow.disabled_at.is_(None),
                    WorkspaceMembershipRow.suspended_at.is_(None),
                )
            ).first()
            if result is None:
                raise KeyError("session not found")
            session_row, user, membership, tenant, sso_config = result
            return {
                "id": session_row.id,
                "user_id": session_row.user_id,
                "owner_id": session_row.owner_id,
                "token_hash": session_row.token_hash,
                "csrf_hash": session_row.csrf_hash,
                "created_at": session_row.created_at,
                "expires_at": session_row.expires_at,
                "mfa_authenticated_at": session_row.mfa_authenticated_at,
                "auth_method": session_row.auth_method,
                "sso_owner_id": session_row.sso_owner_id,
                "last_seen_at": session_row.last_seen_at,
                "created_ip": session_row.created_ip,
                "last_seen_ip": session_row.last_seen_ip,
                "user_agent": session_row.user_agent,
                "role": membership.role,
                "email": user.email,
                "display_name": user.display_name,
                "email_verified_at": user.email_verified_at,
                "mfa_enabled_at": user.mfa_enabled_at,
                "workspace_name": tenant.name,
                "workspace_require_mfa": tenant.require_mfa,
                "workspace_enforce_sso": bool(
                    sso_config
                    and sso_config.enabled
                    and sso_config.enforce_sso
                ),
            }

    def touch_session(
        self,
        session_id: str,
        *,
        client_ip: str | None = None,
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(UserSessionRow, session_id)
            if row is not None:
                row.last_seen_at = datetime.now(UTC)
                if client_ip:
                    row.last_seen_ip = client_ip[:64]

    def list_sessions(self, *, user_id: str) -> list[dict]:
        now = datetime.now(UTC)
        with self._sessions() as session:
            rows = session.scalars(
                select(UserSessionRow)
                .where(
                    UserSessionRow.user_id == user_id,
                    UserSessionRow.revoked_at.is_(None),
                    UserSessionRow.expires_at > now,
                )
                .order_by(UserSessionRow.last_seen_at.desc())
            ).all()
            return [
                {
                    "id": row.id,
                    "owner_id": row.owner_id,
                    "created_at": row.created_at,
                    "expires_at": row.expires_at,
                    "mfa_authenticated_at": row.mfa_authenticated_at,
                    "auth_method": row.auth_method,
                    "sso_owner_id": row.sso_owner_id,
                    "last_seen_at": row.last_seen_at,
                    "created_ip": row.created_ip,
                    "last_seen_ip": row.last_seen_ip,
                    "user_agent": row.user_agent,
                }
                for row in rows
            ]

    def revoke_session(self, session_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(UserSessionRow, session_id)
            if row is not None and row.revoked_at is None:
                row.revoked_at = datetime.now(UTC)

    def revoke_user_session(self, *, user_id: str, session_id: str) -> bool:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(UserSessionRow).where(
                    UserSessionRow.id == session_id,
                    UserSessionRow.user_id == user_id,
                    UserSessionRow.revoked_at.is_(None),
                )
            )
            if row is None:
                return False
            row.revoked_at = datetime.now(UTC)
            return True

    def revoke_other_sessions(
        self,
        *,
        user_id: str,
        keep_session_id: str,
    ) -> int:
        with self._sessions.begin() as session:
            rows = session.scalars(
                select(UserSessionRow).where(
                    UserSessionRow.user_id == user_id,
                    UserSessionRow.id != keep_session_id,
                    UserSessionRow.revoked_at.is_(None),
                )
            ).all()
            now = datetime.now(UTC)
            for row in rows:
                row.revoked_at = now
            return len(rows)

    def revoke_all_sessions(self, *, user_id: str) -> int:
        with self._sessions.begin() as session:
            rows = session.scalars(
                select(UserSessionRow).where(
                    UserSessionRow.user_id == user_id,
                    UserSessionRow.revoked_at.is_(None),
                )
            ).all()
            now = datetime.now(UTC)
            for row in rows:
                row.revoked_at = now
            return len(rows)

    def revoke_workspace_sessions(
        self,
        *,
        user_id: str,
        owner_id: str,
    ) -> int:
        with self._sessions.begin() as session:
            rows = session.scalars(
                select(UserSessionRow).where(
                    UserSessionRow.user_id == user_id,
                    UserSessionRow.owner_id == owner_id,
                    UserSessionRow.revoked_at.is_(None),
                )
            ).all()
            now = datetime.now(UTC)
            for row in rows:
                row.revoked_at = now
            return len(rows)

    def update_password(self, *, user_id: str, password_hash: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError("user not found")
            row.password_hash = password_hash

    def create_account_token(
        self,
        *,
        user_id: str,
        token_type: str,
        token_hash: str,
        expires_at: datetime,
        details: dict | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        token_id = str(uuid4())
        with self._sessions.begin() as session:
            existing = session.scalars(
                select(AccountTokenRow).where(
                    AccountTokenRow.user_id == user_id,
                    AccountTokenRow.token_type == token_type,
                    AccountTokenRow.used_at.is_(None),
                )
            ).all()
            for row in existing:
                row.used_at = now
            created = AccountTokenRow(
                id=token_id,
                user_id=user_id,
                token_type=token_type,
                token_hash=token_hash,
                expires_at=expires_at,
                details=details,
            )
            session.add(created)
            session.flush()
            return self._serialize_account_token(created)

    def get_account_token(
        self,
        *,
        token_type: str,
        token_hash: str,
    ) -> dict:
        now = datetime.now(UTC)
        with self._sessions() as session:
            row = session.scalar(
                select(AccountTokenRow).where(
                    AccountTokenRow.token_type == token_type,
                    AccountTokenRow.token_hash == token_hash,
                    AccountTokenRow.used_at.is_(None),
                )
            )
            if row is None:
                raise KeyError("account token not found")
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                raise KeyError("account token not found")
            return self._serialize_account_token(row)

    def consume_account_token(self, token_id: str) -> dict:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.get(AccountTokenRow, token_id)
            if row is None or row.used_at is not None:
                raise KeyError("account token not found")
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                raise KeyError("account token not found")
            row.used_at = now
            session.flush()
            return self._serialize_account_token(row)

    def mark_email_verified(self, *, user_id: str) -> dict:
        with self._sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError("user not found")
            if row.email_verified_at is None:
                row.email_verified_at = datetime.now(UTC)
            session.flush()
            return self._serialize_user(row)

    def register_login_failure(
        self,
        *,
        user_id: str,
        max_failures: int,
        lock_until: datetime,
    ) -> dict:
        with self._sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError("user not found")
            row.failed_login_count += 1
            if row.failed_login_count >= max_failures:
                row.locked_until = lock_until
            session.flush()
            return self._serialize_user(row)

    def record_login_success(
        self,
        *,
        user_id: str,
        client_ip: str | None,
    ) -> dict:
        with self._sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError("user not found")
            row.failed_login_count = 0
            row.locked_until = None
            row.last_login_at = datetime.now(UTC)
            row.last_login_ip = client_ip[:64] if client_ip else None
            session.flush()
            return self._serialize_user(row)

    def reset_login_security(self, *, user_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError("user not found")
            row.failed_login_count = 0
            row.locked_until = None

    def record_auth_event(
        self,
        *,
        email: str,
        event_type: str,
        success: bool,
        user_id: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        details: dict | None = None,
    ) -> dict:
        with self._sessions.begin() as session:
            row = AuthEventRow(
                id=str(uuid4()),
                user_id=user_id,
                email=email[:320],
                event_type=event_type[:64],
                success=success,
                client_ip=client_ip[:64] if client_ip else None,
                user_agent=user_agent[:512] if user_agent else None,
                details=details,
            )
            session.add(row)
            session.flush()
            return self._serialize_auth_event(row)

    def list_auth_events(self, *, user_id: str, limit: int = 100) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(AuthEventRow)
                .where(AuthEventRow.user_id == user_id)
                .order_by(AuthEventRow.created_at.desc(), AuthEventRow.id.desc())
                .limit(min(max(limit, 1), 500))
            ).all()
            return [self._serialize_auth_event(row) for row in rows]

    def get_workspace_security_policy(self, *, owner_id: str) -> dict:
        with self._sessions() as session:
            tenant = session.get(TenantRow, owner_id)
            if tenant is None:
                raise KeyError("workspace not found")
            return {"owner_id": tenant.id, "require_mfa": tenant.require_mfa}

    def set_workspace_require_mfa(
        self,
        *,
        owner_id: str,
        require_mfa: bool,
    ) -> dict:
        with self._sessions.begin() as session:
            tenant = session.get(TenantRow, owner_id)
            if tenant is None:
                raise KeyError("workspace not found")
            tenant.require_mfa = require_mfa
            session.flush()
            return {"owner_id": tenant.id, "require_mfa": tenant.require_mfa}

    def set_mfa_secret(self, *, user_id: str, encrypted_secret: str) -> dict:
        with self._sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError("user not found")
            row.mfa_secret_encrypted = encrypted_secret
            row.mfa_enabled_at = None
            row.mfa_last_verified_at = None
            session.flush()
            return self._serialize_user(row)

    def enable_mfa(self, *, user_id: str) -> dict:
        with self._sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None or not row.mfa_secret_encrypted:
                raise KeyError("MFA enrollment not found")
            now = datetime.now(UTC)
            row.mfa_enabled_at = now
            row.mfa_last_verified_at = now
            session.flush()
            return self._serialize_user(row)

    def disable_mfa(self, *, user_id: str) -> dict:
        with self._sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                raise KeyError("user not found")
            row.mfa_secret_encrypted = None
            row.mfa_enabled_at = None
            row.mfa_last_verified_at = None
            session.flush()
            return self._serialize_user(row)

    def mark_mfa_verified(self, *, user_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(UserRow, user_id)
            if row is not None:
                row.mfa_last_verified_at = datetime.now(UTC)

    def mark_session_mfa_authenticated(self, *, session_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(UserSessionRow, session_id)
            if row is None:
                raise KeyError("session not found")
            row.mfa_authenticated_at = datetime.now(UTC)

    def replace_recovery_codes(
        self,
        *,
        user_id: str,
        code_hashes: list[str],
    ) -> None:
        with self._sessions.begin() as session:
            old = session.scalars(
                select(MfaRecoveryCodeRow).where(
                    MfaRecoveryCodeRow.user_id == user_id
                )
            ).all()
            for row in old:
                session.delete(row)
            for code_hash in code_hashes:
                session.add(
                    MfaRecoveryCodeRow(
                        id=str(uuid4()),
                        user_id=user_id,
                        code_hash=code_hash,
                    )
                )

    def consume_recovery_code(self, *, user_id: str, code_hash: str) -> bool:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(MfaRecoveryCodeRow).where(
                    MfaRecoveryCodeRow.user_id == user_id,
                    MfaRecoveryCodeRow.code_hash == code_hash,
                    MfaRecoveryCodeRow.used_at.is_(None),
                )
            )
            if row is None:
                return False
            row.used_at = datetime.now(UTC)
            return True

    def count_recovery_codes(self, *, user_id: str) -> int:
        with self._sessions() as session:
            count = session.scalar(
                select(func.count(MfaRecoveryCodeRow.id)).where(
                    MfaRecoveryCodeRow.user_id == user_id,
                    MfaRecoveryCodeRow.used_at.is_(None),
                )
            )
            return int(count or 0)

    def clear_recovery_codes(self, *, user_id: str) -> None:
        with self._sessions.begin() as session:
            rows = session.scalars(
                select(MfaRecoveryCodeRow).where(
                    MfaRecoveryCodeRow.user_id == user_id
                )
            ).all()
            for row in rows:
                session.delete(row)

    def create_trusted_device(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
        client_ip: str | None,
        user_agent: str | None,
    ) -> dict:
        with self._sessions.begin() as session:
            row = TrustedDeviceRow(
                id=str(uuid4()),
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                created_ip=client_ip[:64] if client_ip else None,
                user_agent=user_agent[:512] if user_agent else None,
            )
            session.add(row)
            session.flush()
            return self._serialize_trusted_device(row)

    def authenticate_trusted_device(
        self,
        *,
        user_id: str,
        token_hash: str,
    ) -> dict | None:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.scalar(
                select(TrustedDeviceRow).where(
                    TrustedDeviceRow.user_id == user_id,
                    TrustedDeviceRow.token_hash == token_hash,
                    TrustedDeviceRow.revoked_at.is_(None),
                    TrustedDeviceRow.expires_at > now,
                )
            )
            if row is None:
                return None
            row.last_used_at = now
            session.flush()
            return self._serialize_trusted_device(row)

    def revoke_trusted_devices(self, *, user_id: str) -> int:
        with self._sessions.begin() as session:
            rows = session.scalars(
                select(TrustedDeviceRow).where(
                    TrustedDeviceRow.user_id == user_id,
                    TrustedDeviceRow.revoked_at.is_(None),
                )
            ).all()
            now = datetime.now(UTC)
            for row in rows:
                row.revoked_at = now
            return len(rows)

    def create_invitation(
        self,
        *,
        owner_id: str,
        email: str,
        role: str,
        token_hash: str,
        created_by_user_id: str | None,
        expires_at: datetime,
    ) -> dict:
        invitation_id = str(uuid4())
        with self._sessions.begin() as session:
            row = WorkspaceInvitationRow(
                id=invitation_id,
                owner_id=owner_id,
                email=email,
                role=role,
                token_hash=token_hash,
                created_by_user_id=created_by_user_id,
                expires_at=expires_at,
            )
            session.add(row)
        return self.get_invitation_by_hash(token_hash)

    def get_invitation_by_hash(self, token_hash: str) -> dict:
        with self._sessions() as session:
            result = session.execute(
                select(WorkspaceInvitationRow, TenantRow)
                .join(TenantRow, TenantRow.id == WorkspaceInvitationRow.owner_id)
                .where(WorkspaceInvitationRow.token_hash == token_hash)
            ).first()
            if result is None:
                raise KeyError("invitation not found")
            row, tenant = result
            return {
                **self._serialize_invitation(row),
                "workspace_name": tenant.name,
            }

    def list_invitations(self, *, owner_id: str) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(WorkspaceInvitationRow)
                .where(WorkspaceInvitationRow.owner_id == owner_id)
                .order_by(WorkspaceInvitationRow.created_at.desc())
            ).all()
            return [self._serialize_invitation(row) for row in rows]

    def accept_invitation(
        self,
        *,
        invitation_id: str,
        user_id: str,
    ) -> dict:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            invitation = session.get(WorkspaceInvitationRow, invitation_id)
            user = session.get(UserRow, user_id)
            if invitation is None or user is None:
                raise KeyError("invitation not found")
            if invitation.accepted_at is not None:
                raise ValueError("invitation has already been accepted")
            expires_at = invitation.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                raise ValueError("invitation has expired")
            if user.email != invitation.email:
                raise ValueError("invitation email does not match account")

            membership = session.scalar(
                select(WorkspaceMembershipRow).where(
                    WorkspaceMembershipRow.owner_id == invitation.owner_id,
                    WorkspaceMembershipRow.user_id == user_id,
                )
            )
            if membership is None:
                membership = WorkspaceMembershipRow(
                    id=str(uuid4()),
                    owner_id=invitation.owner_id,
                    user_id=user_id,
                    role=invitation.role,
                )
                session.add(membership)
                session.flush()
            invitation.accepted_at = now
            return self._serialize_membership(membership)

    @staticmethod
    def _serialize_user(row: UserRow) -> dict:
        return {
            "id": row.id,
            "email": row.email,
            "password_hash": row.password_hash,
            "display_name": row.display_name,
            "email_verified_at": row.email_verified_at,
            "failed_login_count": row.failed_login_count,
            "locked_until": row.locked_until,
            "last_login_at": row.last_login_at,
            "last_login_ip": row.last_login_ip,
            "mfa_secret_encrypted": row.mfa_secret_encrypted,
            "mfa_enabled_at": row.mfa_enabled_at,
            "mfa_last_verified_at": row.mfa_last_verified_at,
            "created_at": row.created_at,
            "disabled_at": row.disabled_at,
        }

    @staticmethod
    def _serialize_account_token(row: AccountTokenRow) -> dict:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "token_type": row.token_type,
            "token_hash": row.token_hash,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "used_at": row.used_at,
            "details": row.details,
        }

    @staticmethod
    def _serialize_trusted_device(row: TrustedDeviceRow) -> dict:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "last_used_at": row.last_used_at,
            "created_ip": row.created_ip,
            "user_agent": row.user_agent,
            "revoked_at": row.revoked_at,
        }

    @staticmethod
    def _serialize_auth_event(row: AuthEventRow) -> dict:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "email": row.email,
            "event_type": row.event_type,
            "success": row.success,
            "client_ip": row.client_ip,
            "user_agent": row.user_agent,
            "details": row.details,
            "created_at": row.created_at,
        }

    @staticmethod
    def _serialize_membership(row: WorkspaceMembershipRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "user_id": row.user_id,
            "role": row.role,
            "suspended_at": row.suspended_at,
            "scim_managed": row.scim_managed,
            "scim_external_id": row.scim_external_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _serialize_invitation(row: WorkspaceInvitationRow) -> dict:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "email": row.email,
            "role": row.role,
            "created_by_user_id": row.created_by_user_id,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "accepted_at": row.accepted_at,
        }
