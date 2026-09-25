from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .models import (
    ScimGroupMemberRow,
    ScimGroupRow,
    TenantRow,
    UserRow,
    UserSessionRow,
    WorkspaceMembershipRow,
    WorkspaceScimConfigRow,
)


SCIM_ROLES = {"admin", "analyst", "viewer"}
ROLE_PRIORITY = {"admin": 3, "analyst": 2, "viewer": 1}


class ScimRepository:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def get_config(self, *, owner_id: str) -> dict | None:
        with self._sessions() as session:
            row = session.get(WorkspaceScimConfigRow, owner_id)
            return self._serialize_config(row) if row else None

    def get_config_by_prefix(self, *, token_prefix: str) -> dict | None:
        with self._sessions() as session:
            row = session.scalar(
                select(WorkspaceScimConfigRow).where(
                    WorkspaceScimConfigRow.token_prefix == token_prefix
                )
            )
            return self._serialize_config(row) if row else None

    def upsert_config(
        self,
        *,
        owner_id: str,
        enabled: bool,
        default_role: str,
    ) -> dict:
        if default_role not in SCIM_ROLES:
            raise ValueError("SCIM default role must be admin, analyst, or viewer")
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            tenant = session.get(TenantRow, owner_id)
            if tenant is None:
                raise KeyError("workspace not found")
            row = session.get(WorkspaceScimConfigRow, owner_id)
            if row is None:
                row = WorkspaceScimConfigRow(
                    owner_id=owner_id,
                    enabled=enabled,
                    default_role=default_role,
                )
                session.add(row)
            else:
                row.enabled = enabled
                row.default_role = default_role
                row.updated_at = now
            session.flush()
            return self._serialize_config(row)

    def set_token(
        self,
        *,
        owner_id: str,
        token_prefix: str,
        token_hash: str,
    ) -> dict:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            tenant = session.get(TenantRow, owner_id)
            if tenant is None:
                raise KeyError("workspace not found")
            row = session.get(WorkspaceScimConfigRow, owner_id)
            if row is None:
                row = WorkspaceScimConfigRow(
                    owner_id=owner_id,
                    token_prefix=token_prefix,
                    token_hash=token_hash,
                    enabled=True,
                    default_role="viewer",
                )
                session.add(row)
            else:
                row.token_prefix = token_prefix
                row.token_hash = token_hash
                row.enabled = True
                row.updated_at = now
            session.flush()
            return self._serialize_config(row)

    def list_scim_users(
        self,
        *,
        owner_id: str,
        email: str | None = None,
        external_id: str | None = None,
    ) -> list[dict]:
        with self._sessions() as session:
            stmt = (
                select(WorkspaceMembershipRow, UserRow)
                .join(UserRow, UserRow.id == WorkspaceMembershipRow.user_id)
                .where(
                    WorkspaceMembershipRow.owner_id == owner_id,
                    WorkspaceMembershipRow.scim_managed.is_(True),
                )
                .order_by(UserRow.email, WorkspaceMembershipRow.id)
            )
            if email is not None:
                stmt = stmt.where(UserRow.email == email)
            if external_id is not None:
                stmt = stmt.where(
                    WorkspaceMembershipRow.scim_external_id == external_id
                )
            rows = session.execute(stmt).all()
            return [
                self._serialize_scim_user(membership, user)
                for membership, user in rows
            ]

    def get_scim_user(
        self,
        *,
        owner_id: str,
        membership_id: str,
    ) -> dict:
        with self._sessions() as session:
            result = session.execute(
                select(WorkspaceMembershipRow, UserRow)
                .join(UserRow, UserRow.id == WorkspaceMembershipRow.user_id)
                .where(
                    WorkspaceMembershipRow.id == membership_id,
                    WorkspaceMembershipRow.owner_id == owner_id,
                    WorkspaceMembershipRow.scim_managed.is_(True),
                )
            ).first()
            if result is None:
                raise KeyError("SCIM user not found")
            membership, user = result
            return self._serialize_scim_user(membership, user)

    def provision_user(
        self,
        *,
        owner_id: str,
        email: str,
        display_name: str,
        password_hash: str,
        external_id: str | None,
        role: str,
        active: bool,
    ) -> dict:
        if role not in SCIM_ROLES:
            raise ValueError("SCIM cannot provision owner role")
        now = datetime.now(UTC)
        try:
            with self._sessions.begin() as session:
                tenant = session.get(TenantRow, owner_id)
                if tenant is None:
                    raise KeyError("workspace not found")

                user = session.scalar(
                    select(UserRow).where(UserRow.email == email)
                )
                if user is None:
                    user = UserRow(
                        id=str(uuid4()),
                        email=email,
                        password_hash=password_hash,
                        display_name=display_name,
                        email_verified_at=now,
                    )
                    session.add(user)
                    session.flush()

                membership = session.scalar(
                    select(WorkspaceMembershipRow).where(
                        WorkspaceMembershipRow.owner_id == owner_id,
                        WorkspaceMembershipRow.user_id == user.id,
                    )
                )
                if membership is None:
                    membership = WorkspaceMembershipRow(
                        id=str(uuid4()),
                        owner_id=owner_id,
                        user_id=user.id,
                        role=role,
                        suspended_at=None if active else now,
                        scim_managed=True,
                        scim_external_id=external_id,
                    )
                    session.add(membership)
                else:
                    if membership.role == "owner":
                        raise ValueError("SCIM cannot manage a workspace owner")
                    membership.role = role
                    membership.scim_managed = True
                    membership.scim_external_id = external_id
                    membership.suspended_at = None if active else now
                    membership.updated_at = now

                if display_name:
                    user.display_name = display_name
                session.flush()
                return self._serialize_scim_user(membership, user)
        except IntegrityError:
            raise ValueError("SCIM externalId or userName already exists") from None

    def update_scim_user(
        self,
        *,
        owner_id: str,
        membership_id: str,
        display_name: str | None = None,
        external_id: str | None = None,
        active: bool | None = None,
        role: str | None = None,
    ) -> dict:
        if role is not None and role not in SCIM_ROLES:
            raise ValueError("SCIM cannot provision owner role")
        now = datetime.now(UTC)
        try:
            with self._sessions.begin() as session:
                result = session.execute(
                    select(WorkspaceMembershipRow, UserRow)
                    .join(UserRow, UserRow.id == WorkspaceMembershipRow.user_id)
                    .where(
                        WorkspaceMembershipRow.id == membership_id,
                        WorkspaceMembershipRow.owner_id == owner_id,
                        WorkspaceMembershipRow.scim_managed.is_(True),
                    )
                ).first()
                if result is None:
                    raise KeyError("SCIM user not found")
                membership, user = result
                if membership.role == "owner":
                    raise ValueError("SCIM cannot manage a workspace owner")
                if display_name is not None and display_name.strip():
                    user.display_name = display_name.strip()
                if external_id is not None:
                    membership.scim_external_id = external_id or None
                if role is not None:
                    membership.role = role
                if active is not None:
                    membership.suspended_at = None if active else now
                membership.updated_at = now
                if active is False:
                    self._revoke_workspace_sessions_in_session(
                        session,
                        user_id=membership.user_id,
                        owner_id=owner_id,
                    )
                session.flush()
                return self._serialize_scim_user(membership, user)
        except IntegrityError:
            raise ValueError("SCIM externalId already exists") from None

    def suspend_scim_user(
        self,
        *,
        owner_id: str,
        membership_id: str,
    ) -> dict:
        return self.update_scim_user(
            owner_id=owner_id,
            membership_id=membership_id,
            active=False,
        )

    def list_groups(self, *, owner_id: str) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ScimGroupRow)
                .where(ScimGroupRow.owner_id == owner_id)
                .order_by(ScimGroupRow.display_name, ScimGroupRow.id)
            ).all()
            return [
                self._serialize_group(session, row)
                for row in rows
            ]

    def get_group(self, *, owner_id: str, group_id: str) -> dict:
        with self._sessions() as session:
            row = session.scalar(
                select(ScimGroupRow).where(
                    ScimGroupRow.id == group_id,
                    ScimGroupRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise KeyError("SCIM group not found")
            return self._serialize_group(session, row)

    def find_group_by_display_name(
        self,
        *,
        owner_id: str,
        display_name: str,
    ) -> list[dict]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ScimGroupRow).where(
                    ScimGroupRow.owner_id == owner_id,
                    func.lower(ScimGroupRow.display_name) == display_name.lower(),
                )
            ).all()
            return [self._serialize_group(session, row) for row in rows]

    def create_group(
        self,
        *,
        owner_id: str,
        display_name: str,
        external_id: str | None,
        membership_ids: list[str],
    ) -> dict:
        try:
            with self._sessions.begin() as session:
                if session.get(TenantRow, owner_id) is None:
                    raise KeyError("workspace not found")
                row = ScimGroupRow(
                    id=str(uuid4()),
                    owner_id=owner_id,
                    display_name=display_name,
                    external_id=external_id,
                )
                session.add(row)
                session.flush()
                self._replace_group_members(
                    session,
                    group=row,
                    membership_ids=membership_ids,
                )
                session.flush()
                return self._serialize_group(session, row)
        except IntegrityError:
            raise ValueError("SCIM group externalId already exists") from None

    def update_group(
        self,
        *,
        owner_id: str,
        group_id: str,
        display_name: str | None = None,
        external_id: str | None = None,
        membership_ids: list[str] | None = None,
    ) -> dict:
        try:
            with self._sessions.begin() as session:
                row = session.scalar(
                    select(ScimGroupRow).where(
                        ScimGroupRow.id == group_id,
                        ScimGroupRow.owner_id == owner_id,
                    )
                )
                if row is None:
                    raise KeyError("SCIM group not found")
                affected = self._group_membership_ids(session, group_id=row.id)
                if display_name is not None and display_name.strip():
                    row.display_name = display_name.strip()
                if external_id is not None:
                    row.external_id = external_id or None
                if membership_ids is not None:
                    self._replace_group_members(
                        session,
                        group=row,
                        membership_ids=membership_ids,
                    )
                    affected.update(membership_ids)
                row.updated_at = datetime.now(UTC)
                for membership_id in affected:
                    self._recompute_role(session, owner_id, membership_id)
                session.flush()
                return self._serialize_group(session, row)
        except IntegrityError:
            raise ValueError("SCIM group externalId already exists") from None

    def patch_group_members(
        self,
        *,
        owner_id: str,
        group_id: str,
        add_ids: list[str] | None = None,
        remove_ids: list[str] | None = None,
    ) -> dict:
        add_set = set(add_ids or [])
        remove_set = set(remove_ids or [])
        with self._sessions.begin() as session:
            group = session.scalar(
                select(ScimGroupRow).where(
                    ScimGroupRow.id == group_id,
                    ScimGroupRow.owner_id == owner_id,
                )
            )
            if group is None:
                raise KeyError("SCIM group not found")
            existing = self._group_membership_ids(session, group_id=group.id)
            desired = (existing | add_set) - remove_set
            self._replace_group_members(
                session,
                group=group,
                membership_ids=sorted(desired),
            )
            for membership_id in existing | add_set | remove_set:
                self._recompute_role(session, owner_id, membership_id)
            group.updated_at = datetime.now(UTC)
            session.flush()
            return self._serialize_group(session, group)

    def set_group_role(
        self,
        *,
        owner_id: str,
        group_id: str,
        mapped_role: str | None,
    ) -> dict:
        if mapped_role is not None and mapped_role not in SCIM_ROLES:
            raise ValueError("SCIM group role must be admin, analyst, viewer, or null")
        with self._sessions.begin() as session:
            group = session.scalar(
                select(ScimGroupRow).where(
                    ScimGroupRow.id == group_id,
                    ScimGroupRow.owner_id == owner_id,
                )
            )
            if group is None:
                raise KeyError("SCIM group not found")
            group.mapped_role = mapped_role
            group.updated_at = datetime.now(UTC)
            membership_ids = self._group_membership_ids(
                session,
                group_id=group.id,
            )
            for membership_id in membership_ids:
                self._recompute_role(session, owner_id, membership_id)
            session.flush()
            return self._serialize_group(session, group)

    def delete_group(self, *, owner_id: str, group_id: str) -> None:
        with self._sessions.begin() as session:
            group = session.scalar(
                select(ScimGroupRow).where(
                    ScimGroupRow.id == group_id,
                    ScimGroupRow.owner_id == owner_id,
                )
            )
            if group is None:
                raise KeyError("SCIM group not found")
            membership_ids = self._group_membership_ids(
                session,
                group_id=group.id,
            )
            session.execute(
                delete(ScimGroupMemberRow).where(
                    ScimGroupMemberRow.group_id == group.id
                )
            )
            session.delete(group)
            session.flush()
            for membership_id in membership_ids:
                self._recompute_role(session, owner_id, membership_id)

    def _replace_group_members(
        self,
        session,
        *,
        group: ScimGroupRow,
        membership_ids: list[str],
    ) -> None:
        unique_ids = list(dict.fromkeys(membership_ids))
        if unique_ids:
            valid_rows = session.scalars(
                select(WorkspaceMembershipRow).where(
                    WorkspaceMembershipRow.owner_id == group.owner_id,
                    WorkspaceMembershipRow.id.in_(unique_ids),
                    WorkspaceMembershipRow.scim_managed.is_(True),
                )
            ).all()
            valid_ids = {row.id for row in valid_rows}
            if valid_ids != set(unique_ids):
                raise ValueError("group contains an unknown SCIM user")
        session.execute(
            delete(ScimGroupMemberRow).where(
                ScimGroupMemberRow.group_id == group.id
            )
        )
        for membership_id in unique_ids:
            session.add(
                ScimGroupMemberRow(
                    id=str(uuid4()),
                    group_id=group.id,
                    membership_id=membership_id,
                )
            )
        affected = set(unique_ids)
        for membership_id in affected:
            self._recompute_role(session, group.owner_id, membership_id)

    def _group_membership_ids(self, session, *, group_id: str) -> set[str]:
        return set(
            session.scalars(
                select(ScimGroupMemberRow.membership_id).where(
                    ScimGroupMemberRow.group_id == group_id
                )
            ).all()
        )

    def _recompute_role(
        self,
        session,
        owner_id: str,
        membership_id: str,
    ) -> None:
        membership = session.scalar(
            select(WorkspaceMembershipRow).where(
                WorkspaceMembershipRow.id == membership_id,
                WorkspaceMembershipRow.owner_id == owner_id,
            )
        )
        if (
            membership is None
            or membership.role == "owner"
            or not membership.scim_managed
        ):
            return
        config = session.get(WorkspaceScimConfigRow, owner_id)
        fallback = (
            config.default_role
            if config is not None and config.default_role in SCIM_ROLES
            else "viewer"
        )
        roles = session.scalars(
            select(ScimGroupRow.mapped_role)
            .join(
                ScimGroupMemberRow,
                ScimGroupMemberRow.group_id == ScimGroupRow.id,
            )
            .where(
                ScimGroupMemberRow.membership_id == membership_id,
                ScimGroupRow.owner_id == owner_id,
                ScimGroupRow.mapped_role.is_not(None),
            )
        ).all()
        valid_roles = [role for role in roles if role in SCIM_ROLES]
        membership.role = (
            max(valid_roles, key=lambda item: ROLE_PRIORITY[item])
            if valid_roles
            else fallback
        )
        membership.updated_at = datetime.now(UTC)

    @staticmethod
    def _revoke_workspace_sessions_in_session(
        session,
        *,
        user_id: str,
        owner_id: str,
    ) -> None:
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

    @staticmethod
    def _serialize_config(row: WorkspaceScimConfigRow) -> dict:
        return {
            "owner_id": row.owner_id,
            "token_prefix": row.token_prefix,
            "token_hash": row.token_hash,
            "enabled": row.enabled,
            "default_role": row.default_role,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _serialize_scim_user(
        membership: WorkspaceMembershipRow,
        user: UserRow,
    ) -> dict:
        return {
            "membership_id": membership.id,
            "owner_id": membership.owner_id,
            "user_id": membership.user_id,
            "role": membership.role,
            "active": membership.suspended_at is None,
            "suspended_at": membership.suspended_at,
            "scim_managed": membership.scim_managed,
            "external_id": membership.scim_external_id,
            "created_at": membership.created_at,
            "updated_at": membership.updated_at,
            "email": user.email,
            "display_name": user.display_name,
        }

    @staticmethod
    def _serialize_group(session, row: ScimGroupRow) -> dict:
        member_rows = session.execute(
            select(ScimGroupMemberRow, WorkspaceMembershipRow, UserRow)
            .join(
                WorkspaceMembershipRow,
                WorkspaceMembershipRow.id == ScimGroupMemberRow.membership_id,
            )
            .join(UserRow, UserRow.id == WorkspaceMembershipRow.user_id)
            .where(ScimGroupMemberRow.group_id == row.id)
            .order_by(UserRow.email)
        ).all()
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "external_id": row.external_id,
            "display_name": row.display_name,
            "mapped_role": row.mapped_role,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "members": [
                {
                    "membership_id": membership.id,
                    "user_id": membership.user_id,
                    "email": user.email,
                    "display_name": user.display_name,
                }
                for _, membership, user in member_rows
            ],
        }
