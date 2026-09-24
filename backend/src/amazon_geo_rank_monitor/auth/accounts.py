from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

ROLES = frozenset({"owner", "admin", "analyst", "viewer"})
INVITABLE_ROLES = frozenset({"admin", "analyst", "viewer"})

ROLE_SCOPES: dict[str, frozenset[str]] = {
    "owner": frozenset({"*"}),
    "admin": frozenset(
        {
            "geo:read",
            "geo:write",
            "monitors:read",
            "monitors:write",
            "rank:read",
            "rank:write",
            "billing:read",
            "billing:write",
            "keys:manage",
            "system:read",
            "system:write",
            "team:read",
            "team:manage",
        }
    ),
    "analyst": frozenset(
        {
            "geo:read",
            "geo:write",
            "monitors:read",
            "monitors:write",
            "rank:read",
            "rank:write",
            "billing:read",
            "team:read",
        }
    ),
    "viewer": frozenset(
        {
            "geo:read",
            "monitors:read",
            "rank:read",
            "billing:read",
            "team:read",
        }
    ),
}


@dataclass(frozen=True)
class HumanPrincipal:
    owner_id: str
    user_id: str
    session_id: str
    role: str
    scopes: frozenset[str]
    email: str
    display_name: str
    workspace_name: str
    auth_type: str = "session"
    key_id: None = None

    def allows(self, scope: str) -> bool:
        return "*" in self.scopes or scope in self.scopes


@dataclass(frozen=True)
class SessionCreation:
    plaintext: str
    expires_at: datetime
    principal: HumanPrincipal


@dataclass(frozen=True)
class InvitationCreation:
    id: str
    email: str
    role: str
    plaintext: str
    expires_at: datetime


class AccountService:
    def __init__(
        self,
        *,
        repository,
        session_ttl_hours: int = 720,
        invitation_ttl_hours: int = 168,
    ) -> None:
        if session_ttl_hours < 1:
            raise ValueError("session_ttl_hours must be at least 1")
        if invitation_ttl_hours < 1:
            raise ValueError("invitation_ttl_hours must be at least 1")
        self._repository = repository
        self._passwords = PasswordHasher()
        self._session_ttl = timedelta(hours=session_ttl_hours)
        self._invitation_ttl = timedelta(hours=invitation_ttl_hours)

    @staticmethod
    def normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if (
            not normalized
            or "@" not in normalized
            or normalized.startswith("@")
            or normalized.endswith("@")
        ):
            raise ValueError("a valid email address is required")
        return normalized

    @staticmethod
    def validate_password(password: str) -> None:
        if len(password) < 10:
            raise ValueError("password must be at least 10 characters")

    @staticmethod
    def _token_hash(plaintext: str) -> str:
        return hashlib.sha256(plaintext.encode()).hexdigest()

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        workspace_name: str | None = None,
        invitation_token: str | None = None,
    ) -> SessionCreation:
        normalized_email = self.normalize_email(email)
        self.validate_password(password)
        name = display_name.strip()
        if not name:
            raise ValueError("display name is required")

        password_hash = self._passwords.hash(password)
        if invitation_token:
            invitation = self._load_invitation(invitation_token)
            if invitation["email"] != normalized_email:
                raise ValueError("invitation email does not match account")
            user = self._repository.create_user(
                email=normalized_email,
                password_hash=password_hash,
                display_name=name,
            )
            membership = self._repository.accept_invitation(
                invitation_id=invitation["id"],
                user_id=user["id"],
            )
            return self._issue_session(
                user_id=user["id"],
                owner_id=membership["owner_id"],
            )

        workspace = (workspace_name or "").strip()
        if not workspace:
            raise ValueError("workspace name is required")
        user, membership = self._repository.create_workspace_owner(
            email=normalized_email,
            password_hash=password_hash,
            display_name=name,
            workspace_name=workspace,
        )
        return self._issue_session(
            user_id=user["id"],
            owner_id=membership["owner_id"],
        )

    def bootstrap_owner(
        self,
        *,
        owner_id: str,
        email: str,
        password: str,
        display_name: str,
    ) -> SessionCreation:
        normalized_email = self.normalize_email(email)
        self.validate_password(password)
        name = display_name.strip()
        if not name:
            raise ValueError("display name is required")
        user = self._repository.find_user_by_email(normalized_email)
        if user is not None:
            raise ValueError(
                "account already exists; add the user through a workspace invitation"
            )
        user = self._repository.create_user(
            email=normalized_email,
            password_hash=self._passwords.hash(password),
            display_name=name,
        )
        membership = self._repository.create_owner_membership(
            owner_id=owner_id,
            user_id=user["id"],
        )
        return self._issue_session(
            user_id=user["id"],
            owner_id=membership["owner_id"],
        )

    def login(
        self,
        *,
        email: str,
        password: str,
        workspace_id: str | None = None,
    ) -> SessionCreation:
        normalized_email = self.normalize_email(email)
        user = self._repository.find_user_by_email(normalized_email)
        if user is None or user["disabled_at"] is not None:
            raise ValueError("invalid email or password")
        try:
            self._passwords.verify(user["password_hash"], password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            raise ValueError("invalid email or password") from None

        memberships = self._repository.list_memberships(user_id=user["id"])
        if not memberships:
            raise ValueError("account has no workspace membership")
        membership = (
            next(
                (
                    item
                    for item in memberships
                    if item["owner_id"] == workspace_id
                ),
                None,
            )
            if workspace_id
            else memberships[0]
        )
        if membership is None:
            raise ValueError("workspace membership not found")
        return self._issue_session(
            user_id=user["id"],
            owner_id=membership["owner_id"],
        )

    def authenticate_session(self, plaintext: str) -> HumanPrincipal | None:
        if not plaintext.startswith("agrs_"):
            return None
        try:
            row = self._repository.get_session_by_hash(
                self._token_hash(plaintext)
            )
        except KeyError:
            return None
        self._repository.touch_session(row["id"])
        return self._principal(row)

    def logout(self, session_id: str) -> None:
        self._repository.revoke_session(session_id)

    def switch_workspace(
        self,
        *,
        principal: HumanPrincipal,
        owner_id: str,
    ) -> SessionCreation:
        self._repository.get_membership(
            user_id=principal.user_id,
            owner_id=owner_id,
        )
        self._repository.revoke_session(principal.session_id)
        return self._issue_session(
            user_id=principal.user_id,
            owner_id=owner_id,
        )

    def profile(self, principal: HumanPrincipal) -> dict:
        return {
            "user": {
                "id": principal.user_id,
                "email": principal.email,
                "display_name": principal.display_name,
            },
            "workspace": {
                "id": principal.owner_id,
                "name": principal.workspace_name,
                "role": principal.role,
            },
            "memberships": self._repository.list_memberships(
                user_id=principal.user_id
            ),
        }

    def create_invitation(
        self,
        *,
        principal: HumanPrincipal,
        email: str,
        role: str,
    ) -> InvitationCreation:
        normalized_email = self.normalize_email(email)
        if role not in INVITABLE_ROLES:
            raise ValueError("invitation role must be admin, analyst, or viewer")
        if principal.role == "admin" and role == "admin":
            raise PermissionError("admins cannot invite other admins")
        plaintext = f"agri_{secrets.token_urlsafe(32)}"
        expires_at = datetime.now(UTC) + self._invitation_ttl
        row = self._repository.create_invitation(
            owner_id=principal.owner_id,
            email=normalized_email,
            role=role,
            token_hash=self._token_hash(plaintext),
            created_by_user_id=principal.user_id,
            expires_at=expires_at,
        )
        return InvitationCreation(
            id=row["id"],
            email=row["email"],
            role=row["role"],
            plaintext=plaintext,
            expires_at=expires_at,
        )

    def accept_invitation(
        self,
        *,
        principal: HumanPrincipal,
        invitation_token: str,
    ) -> SessionCreation:
        invitation = self._load_invitation(invitation_token)
        if invitation["email"] != principal.email:
            raise ValueError("invitation email does not match account")
        membership = self._repository.accept_invitation(
            invitation_id=invitation["id"],
            user_id=principal.user_id,
        )
        self._repository.revoke_session(principal.session_id)
        return self._issue_session(
            user_id=principal.user_id,
            owner_id=membership["owner_id"],
        )

    def _load_invitation(self, plaintext: str) -> dict:
        if not plaintext.startswith("agri_"):
            raise ValueError("invalid invitation")
        try:
            invitation = self._repository.get_invitation_by_hash(
                self._token_hash(plaintext)
            )
        except KeyError:
            raise ValueError("invalid invitation") from None
        now = datetime.now(UTC)
        expires_at = invitation["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if invitation["accepted_at"] is not None:
            raise ValueError("invitation has already been accepted")
        if expires_at <= now:
            raise ValueError("invitation has expired")
        return invitation

    def _issue_session(
        self,
        *,
        user_id: str,
        owner_id: str,
    ) -> SessionCreation:
        plaintext = f"agrs_{secrets.token_urlsafe(32)}"
        expires_at = datetime.now(UTC) + self._session_ttl
        row = self._repository.create_session(
            user_id=user_id,
            owner_id=owner_id,
            token_hash=self._token_hash(plaintext),
            expires_at=expires_at,
        )
        return SessionCreation(
            plaintext=plaintext,
            expires_at=expires_at,
            principal=self._principal(row),
        )

    @staticmethod
    def _principal(row: dict) -> HumanPrincipal:
        role = row["role"]
        if role not in ROLE_SCOPES:
            raise ValueError(f"unsupported workspace role: {role}")
        return HumanPrincipal(
            owner_id=row["owner_id"],
            user_id=row["user_id"],
            session_id=row["id"],
            role=role,
            scopes=ROLE_SCOPES[role],
            email=row["email"],
            display_name=row["display_name"],
            workspace_name=row["workspace_name"],
        )
