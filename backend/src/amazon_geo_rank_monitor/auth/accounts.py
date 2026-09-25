from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from amazon_geo_rank_monitor.auth.mfa import (
    MfaCrypto,
    generate_recovery_codes,
    new_mfa_challenge_token,
    new_trusted_device_token,
    normalize_recovery_code,
)

ROLES = frozenset({"owner", "admin", "analyst", "viewer"})
INVITABLE_ROLES = frozenset({"admin", "analyst", "viewer"})

logger = logging.getLogger("amazon_geo_rank_monitor.accounts")


class AccountLockedError(ValueError):
    pass


class SsoRequiredError(ValueError):
    pass


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
    csrf_hash: str
    email_verified_at: datetime | None
    mfa_enabled_at: datetime | None
    mfa_authenticated_at: datetime | None
    workspace_require_mfa: bool
    workspace_enforce_sso: bool
    auth_method: str
    sso_owner_id: str | None
    auth_type: str = "session"
    key_id: None = None

    def allows(self, scope: str) -> bool:
        return "*" in self.scopes or scope in self.scopes


@dataclass(frozen=True)
class SessionCreation:
    plaintext: str
    csrf_token: str
    expires_at: datetime
    principal: HumanPrincipal
    trusted_device_token: str | None = None
    trusted_device_expires_at: datetime | None = None


@dataclass(frozen=True)
class MfaChallenge:
    plaintext: str
    expires_at: datetime


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
        verification_ttl_hours: int = 24,
        password_reset_ttl_minutes: int = 30,
        login_max_failures: int = 5,
        login_lock_minutes: int = 15,
        email_sender=None,
        public_web_url: str = "http://localhost:5173",
        mfa_encryption_key: str = "development-only-change-me",
        mfa_issuer: str = "Amazon Geo Rank Monitor",
        mfa_challenge_minutes: int = 5,
        trusted_device_days: int = 30,
        sso_repository=None,
    ) -> None:
        if session_ttl_hours < 1:
            raise ValueError("session_ttl_hours must be at least 1")
        if invitation_ttl_hours < 1:
            raise ValueError("invitation_ttl_hours must be at least 1")
        if verification_ttl_hours < 1:
            raise ValueError("verification_ttl_hours must be at least 1")
        if password_reset_ttl_minutes < 5:
            raise ValueError("password_reset_ttl_minutes must be at least 5")
        if login_max_failures < 1:
            raise ValueError("login_max_failures must be at least 1")
        if login_lock_minutes < 1:
            raise ValueError("login_lock_minutes must be at least 1")
        if mfa_challenge_minutes < 1:
            raise ValueError("mfa_challenge_minutes must be at least 1")
        if trusted_device_days < 1:
            raise ValueError("trusted_device_days must be at least 1")
        self._repository = repository
        self._passwords = PasswordHasher()
        self._session_ttl = timedelta(hours=session_ttl_hours)
        self._invitation_ttl = timedelta(hours=invitation_ttl_hours)
        self._verification_ttl = timedelta(hours=verification_ttl_hours)
        self._password_reset_ttl = timedelta(minutes=password_reset_ttl_minutes)
        self._login_max_failures = login_max_failures
        self._login_lock = timedelta(minutes=login_lock_minutes)
        self._email_sender = email_sender
        self._public_web_url = public_web_url.rstrip("/")
        self._mfa = MfaCrypto(
            encryption_key=mfa_encryption_key,
            issuer=mfa_issuer,
        )
        self._mfa_challenge_ttl = timedelta(minutes=mfa_challenge_minutes)
        self._trusted_device_ttl = timedelta(days=trusted_device_days)
        self._sso_repository = sso_repository

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
        client_ip: str | None = None,
        user_agent: str | None = None,
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
            self._repository.mark_email_verified(user_id=user["id"])
            self._repository.record_auth_event(
                email=normalized_email,
                event_type="account_registered",
                success=True,
                user_id=user["id"],
                client_ip=client_ip,
                user_agent=user_agent,
                details={"verified_by": "workspace_invitation"},
            )
            return self._issue_session(
                user_id=user["id"],
                owner_id=membership["owner_id"],
                client_ip=client_ip,
                user_agent=user_agent,
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
        self._repository.record_auth_event(
            email=normalized_email,
            event_type="account_registered",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
        )
        self._send_verification(user)
        return self._issue_session(
            user_id=user["id"],
            owner_id=membership["owner_id"],
            client_ip=client_ip,
            user_agent=user_agent,
        )

    def bootstrap_owner(
        self,
        *,
        owner_id: str,
        email: str,
        password: str,
        display_name: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
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
        self._send_verification(user)
        return self._issue_session(
            user_id=user["id"],
            owner_id=membership["owner_id"],
            client_ip=client_ip,
            user_agent=user_agent,
        )

    def login(
        self,
        *,
        email: str,
        password: str,
        workspace_id: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        trusted_device_token: str | None = None,
    ) -> SessionCreation | MfaChallenge:
        normalized_email = self.normalize_email(email)
        user = self._repository.find_user_by_email(normalized_email)
        if user is None or user["disabled_at"] is not None:
            self._repository.record_auth_event(
                email=normalized_email,
                event_type="login_failed",
                success=False,
                user_id=user["id"] if user else None,
                client_ip=client_ip,
                user_agent=user_agent,
            )
            raise ValueError("invalid email or password")

        now = datetime.now(UTC)
        locked_until = user["locked_until"]
        if locked_until is not None:
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=UTC)
            if locked_until > now:
                self._repository.record_auth_event(
                    email=normalized_email,
                    event_type="login_locked",
                    success=False,
                    user_id=user["id"],
                    client_ip=client_ip,
                    user_agent=user_agent,
                    details={"locked_until": locked_until.isoformat()},
                )
                raise AccountLockedError("account temporarily locked")
            self._repository.reset_login_security(user_id=user["id"])

        try:
            self._passwords.verify(user["password_hash"], password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            updated = self._repository.register_login_failure(
                user_id=user["id"],
                max_failures=self._login_max_failures,
                lock_until=now + self._login_lock,
            )
            newly_locked = updated["locked_until"] is not None
            self._repository.record_auth_event(
                email=normalized_email,
                event_type="login_locked" if newly_locked else "login_failed",
                success=False,
                user_id=user["id"],
                client_ip=client_ip,
                user_agent=user_agent,
                details={"failed_login_count": updated["failed_login_count"]},
            )
            if newly_locked:
                raise AccountLockedError("account temporarily locked") from None
            raise ValueError("invalid email or password") from None

        memberships = self._repository.list_memberships(user_id=user["id"])
        if not memberships:
            raise ValueError("account has no workspace membership")
        membership = (
            next((item for item in memberships if item["owner_id"] == workspace_id), None)
            if workspace_id
            else memberships[0]
        )
        if membership is None:
            raise ValueError("workspace membership not found")

        if self._sso_repository is not None:
            sso_config = self._sso_repository.get_config(
                owner_id=membership["owner_id"]
            )
            if sso_config and sso_config["enabled"] and sso_config["enforce_sso"]:
                self._repository.record_auth_event(
                    email=normalized_email,
                    event_type="password_login_blocked_by_sso",
                    success=False,
                    user_id=user["id"],
                    client_ip=client_ip,
                    user_agent=user_agent,
                    details={"owner_id": membership["owner_id"]},
                )
                raise SsoRequiredError("SSO is required for this workspace")

        self._repository.record_login_success(
            user_id=user["id"],
            client_ip=client_ip,
        )

        if user["mfa_enabled_at"] is not None:
            trusted = None
            if trusted_device_token and trusted_device_token.startswith("agrd_"):
                trusted = self._repository.authenticate_trusted_device(
                    user_id=user["id"],
                    token_hash=self._token_hash(trusted_device_token),
                )
            if trusted is not None:
                self._repository.record_auth_event(
                    email=normalized_email,
                    event_type="login_succeeded",
                    success=True,
                    user_id=user["id"],
                    client_ip=client_ip,
                    user_agent=user_agent,
                    details={"mfa": "trusted_device"},
                )
                return self._issue_session(
                    user_id=user["id"],
                    owner_id=membership["owner_id"],
                    client_ip=client_ip,
                    user_agent=user_agent,
                    mfa_authenticated=True,
                )

            challenge = new_mfa_challenge_token()
            expires_at = now + self._mfa_challenge_ttl
            self._repository.create_account_token(
                user_id=user["id"],
                token_type="mfa_login",
                token_hash=self._token_hash(challenge),
                expires_at=expires_at,
                details={"owner_id": membership["owner_id"]},
            )
            self._repository.record_auth_event(
                email=normalized_email,
                event_type="mfa_challenge_issued",
                success=True,
                user_id=user["id"],
                client_ip=client_ip,
                user_agent=user_agent,
            )
            return MfaChallenge(plaintext=challenge, expires_at=expires_at)

        self._repository.record_auth_event(
            email=normalized_email,
            event_type="login_succeeded",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
            details={"mfa": "not_enabled"},
        )
        return self._issue_session(
            user_id=user["id"],
            owner_id=membership["owner_id"],
            client_ip=client_ip,
            user_agent=user_agent,
        )

    def complete_mfa_login(
        self,
        *,
        challenge_token: str,
        code: str,
        remember_device: bool,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> SessionCreation:
        if not challenge_token.startswith("agrmfa_"):
            raise ValueError("invalid or expired MFA challenge")
        try:
            challenge = self._repository.get_account_token(
                token_type="mfa_login",
                token_hash=self._token_hash(challenge_token),
            )
        except KeyError:
            raise ValueError("invalid or expired MFA challenge") from None

        user = self._repository.get_user(challenge["user_id"])
        if user["mfa_enabled_at"] is None or not self._verify_mfa_code(user, code):
            self._repository.record_auth_event(
                email=user["email"],
                event_type="mfa_failed",
                success=False,
                user_id=user["id"],
                client_ip=client_ip,
                user_agent=user_agent,
            )
            raise ValueError("invalid MFA code")

        self._repository.consume_account_token(challenge["id"])
        self._repository.mark_mfa_verified(user_id=user["id"])
        self._repository.record_auth_event(
            email=user["email"],
            event_type="login_succeeded",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
            details={"mfa": "totp_or_recovery"},
        )
        session = self._issue_session(
            user_id=user["id"],
            owner_id=challenge["details"]["owner_id"],
            client_ip=client_ip,
            user_agent=user_agent,
            mfa_authenticated=True,
        )
        if not remember_device:
            return session

        trusted_token = new_trusted_device_token()
        trusted_expires_at = datetime.now(UTC) + self._trusted_device_ttl
        self._repository.create_trusted_device(
            user_id=user["id"],
            token_hash=self._token_hash(trusted_token),
            expires_at=trusted_expires_at,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return SessionCreation(
            plaintext=session.plaintext,
            csrf_token=session.csrf_token,
            expires_at=session.expires_at,
            principal=session.principal,
            trusted_device_token=trusted_token,
            trusted_device_expires_at=trusted_expires_at,
        )

    def create_sso_account(
        self,
        *,
        owner_id: str,
        email: str,
        display_name: str,
    ) -> tuple[dict, dict]:
        normalized_email = self.normalize_email(email)
        user = self._repository.find_user_by_email(normalized_email)
        if user is None:
            user = self._repository.create_user(
                email=normalized_email,
                password_hash=self._passwords.hash(secrets.token_urlsafe(48)),
                display_name=display_name.strip() or normalized_email.split("@", 1)[0],
            )
            self._repository.mark_email_verified(user_id=user["id"])
            user = self._repository.get_user(user["id"])
        try:
            membership = self._repository.get_membership(
                user_id=user["id"],
                owner_id=owner_id,
            )
        except KeyError:
            membership = self._repository.create_membership(
                owner_id=owner_id,
                user_id=user["id"],
                role="viewer",
            )
        return user, membership

    def issue_sso_session(
        self,
        *,
        user_id: str,
        owner_id: str,
        mfa_authenticated: bool,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> SessionCreation:
        return self._issue_session(
            user_id=user_id,
            owner_id=owner_id,
            client_ip=client_ip,
            user_agent=user_agent,
            mfa_authenticated=mfa_authenticated,
            auth_method="sso",
            sso_owner_id=owner_id,
        )

    def authenticate_session(
        self,
        plaintext: str,
        *,
        client_ip: str | None = None,
    ) -> HumanPrincipal | None:
        if not plaintext.startswith("agrs_"):
            return None
        try:
            row = self._repository.get_session_by_hash(self._token_hash(plaintext))
        except KeyError:
            return None
        self._repository.touch_session(row["id"], client_ip=client_ip)
        return self._principal(row)

    def logout(self, session_id: str) -> None:
        self._repository.revoke_session(session_id)

    def switch_workspace(
        self,
        *,
        principal: HumanPrincipal,
        owner_id: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> SessionCreation:
        self._repository.get_membership(user_id=principal.user_id, owner_id=owner_id)
        if self._sso_repository is not None:
            target_sso = self._sso_repository.get_config(owner_id=owner_id)
            if (
                target_sso
                and target_sso["enabled"]
                and target_sso["enforce_sso"]
                and principal.sso_owner_id != owner_id
            ):
                raise SsoRequiredError("SSO is required for this workspace")
        self._repository.revoke_session(principal.session_id)
        return self._issue_session(
            user_id=principal.user_id,
            owner_id=owner_id,
            client_ip=client_ip,
            user_agent=user_agent,
            mfa_authenticated=principal.mfa_authenticated_at is not None,
            auth_method=principal.auth_method,
            sso_owner_id=principal.sso_owner_id,
        )

    def profile(self, principal: HumanPrincipal) -> dict:
        return {
            "user": {
                "id": principal.user_id,
                "email": principal.email,
                "display_name": principal.display_name,
                "email_verified": principal.email_verified_at is not None,
                "email_verified_at": principal.email_verified_at,
                "mfa_enabled": principal.mfa_enabled_at is not None,
                "mfa_authenticated": principal.mfa_authenticated_at is not None,
                "recovery_codes_remaining": self._repository.count_recovery_codes(
                    user_id=principal.user_id
                ),
            },
            "workspace": {
                "id": principal.owner_id,
                "name": principal.workspace_name,
                "role": principal.role,
                "require_mfa": principal.workspace_require_mfa,
                "mfa_setup_required": (
                    principal.workspace_require_mfa
                    and principal.mfa_enabled_at is None
                ),
                "mfa_session_verification_required": (
                    principal.workspace_require_mfa
                    and principal.mfa_enabled_at is not None
                    and principal.mfa_authenticated_at is None
                ),
                "enforce_sso": principal.workspace_enforce_sso,
                "sso_authenticated": (
                    principal.sso_owner_id == principal.owner_id
                ),
            },
            "memberships": self._repository.list_memberships(
                user_id=principal.user_id
            ),
        }

    def begin_mfa_enrollment(self, *, principal: HumanPrincipal) -> dict:
        user = self._repository.get_user(principal.user_id)
        if user["email_verified_at"] is None:
            raise ValueError("verify your email before enabling MFA")
        if user["mfa_enabled_at"] is not None:
            raise ValueError("MFA is already enabled")
        enrollment = self._mfa.begin_enrollment(email=user["email"])
        self._repository.set_mfa_secret(
            user_id=user["id"],
            encrypted_secret=enrollment.encrypted_secret,
        )
        self._repository.record_auth_event(
            email=user["email"],
            event_type="mfa_enrollment_started",
            success=True,
            user_id=user["id"],
        )
        return {
            "secret": enrollment.secret,
            "provisioning_uri": enrollment.provisioning_uri,
        }

    def confirm_mfa_enrollment(
        self,
        *,
        principal: HumanPrincipal,
        code: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> list[str]:
        user = self._repository.get_user(principal.user_id)
        encrypted = user["mfa_secret_encrypted"]
        if not encrypted or not self._mfa.verify_totp(
            encrypted_secret=encrypted,
            code=code,
        ):
            raise ValueError("invalid TOTP code")

        self._repository.enable_mfa(user_id=user["id"])
        self._repository.mark_session_mfa_authenticated(
            session_id=principal.session_id
        )
        recovery_codes = generate_recovery_codes()
        self._repository.replace_recovery_codes(
            user_id=user["id"],
            code_hashes=[
                self._token_hash(normalize_recovery_code(item))
                for item in recovery_codes
            ],
        )
        self._repository.record_auth_event(
            email=user["email"],
            event_type="mfa_enabled",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return recovery_codes

    def verify_current_session_mfa(
        self,
        *,
        principal: HumanPrincipal,
        code: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        user = self._repository.get_user(principal.user_id)
        if user["mfa_enabled_at"] is None or not self._verify_mfa_code(user, code):
            self._repository.record_auth_event(
                email=user["email"],
                event_type="mfa_session_verification_failed",
                success=False,
                user_id=user["id"],
                client_ip=client_ip,
                user_agent=user_agent,
            )
            raise ValueError("valid MFA code required")
        self._repository.mark_mfa_verified(user_id=user["id"])
        self._repository.mark_session_mfa_authenticated(
            session_id=principal.session_id
        )
        self._repository.record_auth_event(
            email=user["email"],
            event_type="mfa_session_verified",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
        )

    def regenerate_recovery_codes(
        self,
        *,
        principal: HumanPrincipal,
        code: str,
    ) -> list[str]:
        user = self._repository.get_user(principal.user_id)
        if user["mfa_enabled_at"] is None or not self._verify_mfa_code(user, code):
            raise ValueError("valid MFA code required")
        recovery_codes = generate_recovery_codes()
        self._repository.replace_recovery_codes(
            user_id=user["id"],
            code_hashes=[
                self._token_hash(normalize_recovery_code(item))
                for item in recovery_codes
            ],
        )
        return recovery_codes

    def disable_mfa(
        self,
        *,
        principal: HumanPrincipal,
        password: str,
        code: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        memberships = self._repository.list_memberships(user_id=principal.user_id)
        if any(item.get("require_mfa") for item in memberships):
            raise ValueError("leave or disable workspace MFA policy before disabling MFA")
        user = self._repository.get_user(principal.user_id)
        try:
            self._passwords.verify(user["password_hash"], password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            raise ValueError("current password is invalid") from None
        if user["mfa_enabled_at"] is None or not self._verify_mfa_code(user, code):
            raise ValueError("valid MFA code required")
        self._repository.disable_mfa(user_id=user["id"])
        self._repository.clear_recovery_codes(user_id=user["id"])
        self._repository.revoke_trusted_devices(user_id=user["id"])
        self._repository.revoke_other_sessions(
            user_id=user["id"],
            keep_session_id=principal.session_id,
        )
        self._repository.record_auth_event(
            email=user["email"],
            event_type="mfa_disabled",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
        )

    def set_workspace_mfa_policy(
        self,
        *,
        principal: HumanPrincipal,
        require_mfa: bool,
    ) -> dict:
        if principal.role != "owner":
            raise PermissionError("only workspace owners can change MFA policy")
        if require_mfa:
            members = self._repository.list_members(owner_id=principal.owner_id)
            missing = [item for item in members if not item.get("mfa_enabled")]
            if missing:
                raise ValueError(
                    f"{len(missing)} workspace member(s) must enable MFA first"
                )
        return self._repository.set_workspace_require_mfa(
            owner_id=principal.owner_id,
            require_mfa=require_mfa,
        )

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
        self._safe_send(
            to=normalized_email,
            subject=f"Join {principal.workspace_name} on Geo Rank Monitor",
            text=(
                f"{principal.display_name} invited you to join "
                f"{principal.workspace_name} as {role}.\n\n"
                f"Open: {self._public_web_url}/#/login?invite={plaintext}\n\n"
                f"This invitation expires at {expires_at.isoformat()}."
            ),
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
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> SessionCreation:
        invitation = self._load_invitation(invitation_token)
        if invitation["email"] != principal.email:
            raise ValueError("invitation email does not match account")
        membership = self._repository.accept_invitation(
            invitation_id=invitation["id"],
            user_id=principal.user_id,
        )
        self._repository.mark_email_verified(user_id=principal.user_id)
        self._repository.record_auth_event(
            email=principal.email,
            event_type="email_verified",
            success=True,
            user_id=principal.user_id,
            client_ip=client_ip,
            user_agent=user_agent,
            details={"verified_by": "workspace_invitation"},
        )
        self._repository.revoke_session(principal.session_id)
        return self._issue_session(
            user_id=principal.user_id,
            owner_id=membership["owner_id"],
            client_ip=client_ip,
            user_agent=user_agent,
            mfa_authenticated=principal.mfa_authenticated_at is not None,
            auth_method=principal.auth_method,
            sso_owner_id=principal.sso_owner_id,
        )

    def resend_verification(
        self,
        *,
        principal: HumanPrincipal,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> bool:
        user = self._repository.get_user(principal.user_id)
        if user["email_verified_at"] is not None:
            return False
        self._send_verification(user)
        self._repository.record_auth_event(
            email=user["email"],
            event_type="verification_resent",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return True

    def verify_email(
        self,
        *,
        token: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict:
        if not token.startswith("agrv_"):
            raise ValueError("invalid or expired verification token")
        try:
            stored = self._repository.get_account_token(
                token_type="email_verification",
                token_hash=self._token_hash(token),
            )
            self._repository.consume_account_token(stored["id"])
        except KeyError:
            raise ValueError("invalid or expired verification token") from None
        user = self._repository.mark_email_verified(user_id=stored["user_id"])
        self._repository.record_auth_event(
            email=user["email"],
            event_type="email_verified",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return user

    def forgot_password(
        self,
        *,
        email: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        normalized_email = self.normalize_email(email)
        user = self._repository.find_user_by_email(normalized_email)
        if user is None or user["disabled_at"] is not None:
            self._repository.record_auth_event(
                email=normalized_email,
                event_type="password_reset_requested",
                success=False,
                user_id=user["id"] if user else None,
                client_ip=client_ip,
                user_agent=user_agent,
            )
            return
        self._send_password_reset(user)
        self._repository.record_auth_event(
            email=normalized_email,
            event_type="password_reset_requested",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
        )

    def reset_password(
        self,
        *,
        token: str,
        new_password: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        self.validate_password(new_password)
        if not token.startswith("agrr_"):
            raise ValueError("invalid or expired reset token")
        try:
            stored = self._repository.get_account_token(
                token_type="password_reset",
                token_hash=self._token_hash(token),
            )
            self._repository.consume_account_token(stored["id"])
        except KeyError:
            raise ValueError("invalid or expired reset token") from None

        user = self._repository.get_user(stored["user_id"])
        self._repository.update_password(
            user_id=user["id"],
            password_hash=self._passwords.hash(new_password),
        )
        self._repository.reset_login_security(user_id=user["id"])
        revoked = self._repository.revoke_all_sessions(user_id=user["id"])
        self._repository.revoke_trusted_devices(user_id=user["id"])
        self._repository.record_auth_event(
            email=user["email"],
            event_type="password_reset_completed",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
            details={"revoked_sessions": revoked},
        )
        return revoked

    def list_auth_events(
        self,
        *,
        principal: HumanPrincipal,
        limit: int = 100,
    ) -> list[dict]:
        return self._repository.list_auth_events(
            user_id=principal.user_id,
            limit=limit,
        )

    def verify_csrf(self, principal: HumanPrincipal, csrf_token: str) -> bool:
        if not csrf_token:
            return False
        return hmac.compare_digest(
            self._token_hash(csrf_token),
            principal.csrf_hash,
        )

    def list_sessions(self, principal: HumanPrincipal) -> list[dict]:
        return [
            {
                **row,
                "current": row["id"] == principal.session_id,
            }
            for row in self._repository.list_sessions(user_id=principal.user_id)
        ]

    def revoke_user_session(
        self,
        *,
        principal: HumanPrincipal,
        session_id: str,
    ) -> bool:
        return self._repository.revoke_user_session(
            user_id=principal.user_id,
            session_id=session_id,
        )

    def logout_all(self, principal: HumanPrincipal) -> int:
        self._repository.revoke_trusted_devices(user_id=principal.user_id)
        return self._repository.revoke_all_sessions(user_id=principal.user_id)

    def change_password(
        self,
        *,
        principal: HumanPrincipal,
        current_password: str,
        new_password: str,
    ) -> int:
        self.validate_password(new_password)
        user = self._repository.get_user(principal.user_id)
        try:
            self._passwords.verify(user["password_hash"], current_password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            raise ValueError("current password is invalid") from None
        if current_password == new_password:
            raise ValueError("new password must be different")
        self._repository.update_password(
            user_id=principal.user_id,
            password_hash=self._passwords.hash(new_password),
        )
        self._repository.revoke_trusted_devices(user_id=principal.user_id)
        return self._repository.revoke_other_sessions(
            user_id=principal.user_id,
            keep_session_id=principal.session_id,
        )

    def rotate_session(
        self,
        *,
        principal: HumanPrincipal,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> SessionCreation:
        self._repository.revoke_session(principal.session_id)
        return self._issue_session(
            user_id=principal.user_id,
            owner_id=principal.owner_id,
            client_ip=client_ip,
            user_agent=user_agent,
            mfa_authenticated=principal.mfa_authenticated_at is not None,
            auth_method=principal.auth_method,
            sso_owner_id=principal.sso_owner_id,
        )

    def _verify_mfa_code(self, user: dict, code: str) -> bool:
        encrypted = user["mfa_secret_encrypted"]
        if encrypted and self._mfa.verify_totp(
            encrypted_secret=encrypted,
            code=code,
        ):
            return True
        normalized = normalize_recovery_code(code)
        if len(normalized) < 8:
            return False
        return self._repository.consume_recovery_code(
            user_id=user["id"],
            code_hash=self._token_hash(normalized),
        )

    def _send_verification(self, user: dict) -> None:
        if user["email_verified_at"] is not None:
            return
        plaintext = f"agrv_{secrets.token_urlsafe(32)}"
        expires_at = datetime.now(UTC) + self._verification_ttl
        self._repository.create_account_token(
            user_id=user["id"],
            token_type="email_verification",
            token_hash=self._token_hash(plaintext),
            expires_at=expires_at,
        )
        self._safe_send(
            to=user["email"],
            subject="Verify your Geo Rank Monitor email",
            text=(
                "Verify your email address to secure your account.\n\n"
                f"Open: {self._public_web_url}/#/verify-email?token={plaintext}\n\n"
                f"This link expires at {expires_at.isoformat()}."
            ),
        )

    def _send_password_reset(self, user: dict) -> None:
        plaintext = f"agrr_{secrets.token_urlsafe(32)}"
        expires_at = datetime.now(UTC) + self._password_reset_ttl
        self._repository.create_account_token(
            user_id=user["id"],
            token_type="password_reset",
            token_hash=self._token_hash(plaintext),
            expires_at=expires_at,
        )
        self._safe_send(
            to=user["email"],
            subject="Reset your Geo Rank Monitor password",
            text=(
                "A password reset was requested for your account.\n\n"
                f"Open: {self._public_web_url}/#/reset-password?token={plaintext}\n\n"
                f"This link expires at {expires_at.isoformat()}. "
                "If you did not request this, ignore this email."
            ),
        )

    def _safe_send(self, *, to: str, subject: str, text: str) -> None:
        if self._email_sender is None:
            return
        try:
            self._email_sender.send(to=to, subject=subject, text=text)
        except Exception:
            logger.exception("account_email_delivery_failed to=%s subject=%s", to, subject)

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
        client_ip: str | None = None,
        user_agent: str | None = None,
        mfa_authenticated: bool = False,
        auth_method: str = "local",
        sso_owner_id: str | None = None,
    ) -> SessionCreation:
        plaintext = f"agrs_{secrets.token_urlsafe(32)}"
        csrf_token = f"agrc_{secrets.token_urlsafe(24)}"
        expires_at = datetime.now(UTC) + self._session_ttl
        row = self._repository.create_session(
            user_id=user_id,
            owner_id=owner_id,
            token_hash=self._token_hash(plaintext),
            csrf_hash=self._token_hash(csrf_token),
            expires_at=expires_at,
            client_ip=client_ip,
            user_agent=user_agent,
            mfa_authenticated=mfa_authenticated,
            auth_method=auth_method,
            sso_owner_id=sso_owner_id,
        )
        return SessionCreation(
            plaintext=plaintext,
            csrf_token=csrf_token,
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
            csrf_hash=row["csrf_hash"],
            email_verified_at=row["email_verified_at"],
            mfa_enabled_at=row["mfa_enabled_at"],
            mfa_authenticated_at=row["mfa_authenticated_at"],
            workspace_require_mfa=bool(row["workspace_require_mfa"]),
            workspace_enforce_sso=bool(row["workspace_enforce_sso"]),
            auth_method=row["auth_method"],
            sso_owner_id=row["sso_owner_id"],
        )
