from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


@dataclass(frozen=True)
class SsoStart:
    authorization_url: str
    expires_at: datetime


@dataclass(frozen=True)
class SsoCompletion:
    session: object
    email: str
    workspace_id: str
    provider_name: str


class OidcSsoService:
    def __init__(
        self,
        *,
        repository,
        account_repository,
        accounts,
        encryption_key: str,
        callback_url: str,
        public_web_url: str,
        transaction_minutes: int = 5,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not encryption_key:
            raise ValueError("SSO encryption key is required")
        if transaction_minutes < 1:
            raise ValueError("SSO transaction TTL must be at least 1 minute")
        digest = hashlib.sha256(encryption_key.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))
        self._repository = repository
        self._account_repository = account_repository
        self._accounts = accounts
        self._callback_url = self._validate_url(callback_url, allow_http_local=True)
        self._public_web_url = public_web_url.rstrip("/")
        self._transaction_ttl = timedelta(minutes=transaction_minutes)
        self._http = http_client or httpx.Client(timeout=10.0, follow_redirects=False)

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _b64url_decode(value: str) -> bytes:
        padding_length = (-len(value)) % 4
        return base64.urlsafe_b64decode(value + ("=" * padding_length))

    @staticmethod
    def _b64url_encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    @staticmethod
    def _validate_url(value: str, *, allow_http_local: bool = False) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("invalid OIDC URL")
        is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        local_http = allow_http_local and is_local and parsed.scheme == "http"
        if parsed.scheme != "https" and not local_http:
            raise ValueError("OIDC URLs must use HTTPS")
        if parsed.query or parsed.fragment:
            raise ValueError("OIDC URL must not include query or fragment")
        return normalized

    @staticmethod
    def normalize_domains(domains: list[str]) -> list[str]:
        normalized = sorted(
            {
                item.strip().lower().lstrip("@")
                for item in domains
                if item.strip()
            }
        )
        if not normalized or any("." not in item for item in normalized):
            raise ValueError("at least one valid email domain is required")
        return normalized

    @staticmethod
    def email_domain(email: str) -> str:
        normalized = email.strip().lower()
        if "@" not in normalized:
            raise ValueError("valid email address required")
        return normalized.rsplit("@", 1)[1]

    @staticmethod
    def _public_config(config: dict | None) -> dict | None:
        if config is None:
            return None
        return {
            key: value
            for key, value in config.items()
            if key != "client_secret_encrypted"
        }

    def get_config(self, *, owner_id: str) -> dict | None:
        return self._public_config(self._repository.get_config(owner_id=owner_id))

    def configure(
        self,
        *,
        owner_id: str,
        provider_type: str,
        display_name: str,
        issuer_url: str,
        client_id: str,
        client_secret: str | None,
        email_domains: list[str],
        auto_join: bool,
        enabled: bool,
    ) -> dict:
        provider = provider_type.strip().lower()
        if provider not in {"google", "entra", "oidc"}:
            raise ValueError("provider_type must be google, entra, or oidc")
        issuer = self._validate_url(issuer_url, allow_http_local=True)
        client = client_id.strip()
        if not client:
            raise ValueError("OIDC client ID is required")
        name = display_name.strip() or "Enterprise SSO"
        domains = self.normalize_domains(email_domains)

        existing = self._repository.get_config(owner_id=owner_id)
        if client_secret and client_secret.strip():
            encrypted_secret = self._encrypt(client_secret.strip())
        elif existing is not None:
            encrypted_secret = existing["client_secret_encrypted"]
        else:
            raise ValueError("OIDC client secret is required")

        stored = self._repository.upsert_config(
            owner_id=owner_id,
            provider_type=provider,
            display_name=name,
            issuer_url=issuer,
            client_id=client,
            client_secret_encrypted=encrypted_secret,
            email_domains=domains,
            auto_join=auto_join,
            enabled=enabled,
        )
        return self._public_config(stored)

    def set_enforcement(self, *, owner_id: str, enforce_sso: bool) -> dict:
        return self._public_config(
            self._repository.set_enforce_sso(
                owner_id=owner_id,
                enforce_sso=enforce_sso,
            )
        )

    def discover(self, *, email: str) -> list[dict]:
        domain = self.email_domain(email)
        results = []
        for config in self._repository.list_enabled_configs():
            if domain in config["email_domains"]:
                results.append(
                    {
                        "workspace_id": config["owner_id"],
                        "display_name": config["display_name"],
                        "provider_type": config["provider_type"],
                    }
                )
        return results

    def start_login(
        self,
        *,
        owner_id: str,
        email_hint: str | None = None,
    ) -> SsoStart:
        config = self._repository.get_config(owner_id=owner_id)
        if config is None or not config["enabled"]:
            raise ValueError("SSO is not enabled for this workspace")
        if email_hint:
            domain = self.email_domain(email_hint)
            if domain not in config["email_domains"]:
                raise ValueError("email domain is not allowed for this workspace")

        metadata = self._discovery(config)
        state = f"agrsso_{secrets.token_urlsafe(32)}"
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = self._b64url_encode(hashlib.sha256(verifier.encode()).digest())
        expires_at = datetime.now(UTC) + self._transaction_ttl
        self._repository.create_transaction(
            owner_id=owner_id,
            state_hash=self._hash(state),
            nonce_hash=self._hash(nonce),
            code_verifier_encrypted=self._encrypt(verifier),
            email_hint=email_hint.strip().lower() if email_hint else None,
            expires_at=expires_at,
        )

        query = {
            "response_type": "code",
            "client_id": config["client_id"],
            "redirect_uri": self._callback_url,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if email_hint:
            query["login_hint"] = email_hint.strip().lower()
        authorization_url = metadata["authorization_endpoint"] + "?" + urlencode(query)
        return SsoStart(
            authorization_url=authorization_url,
            expires_at=expires_at,
        )

    def complete_login(
        self,
        *,
        state: str,
        code: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> SsoCompletion:
        if not state.startswith("agrsso_") or not code:
            raise ValueError("invalid SSO callback")
        try:
            transaction = self._repository.consume_transaction(
                state_hash=self._hash(state)
            )
        except KeyError:
            raise ValueError("invalid or expired SSO transaction") from None

        config = self._repository.get_config(owner_id=transaction["owner_id"])
        if config is None or not config["enabled"]:
            raise ValueError("SSO is no longer enabled")

        metadata = self._discovery(config)
        verifier = self._decrypt(transaction["code_verifier_encrypted"])
        token_endpoint = self._validate_url(
            metadata["token_endpoint"],
            allow_http_local=True,
        )
        token_response = self._http.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._callback_url,
                "client_id": config["client_id"],
                "client_secret": self._decrypt(config["client_secret_encrypted"]),
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
        )
        if token_response.status_code >= 400:
            raise ValueError("OIDC token exchange failed")
        token_payload = token_response.json()
        id_token = token_payload.get("id_token")
        if not isinstance(id_token, str):
            raise ValueError("OIDC provider did not return an ID token")

        claims = self._verify_id_token(
            id_token=id_token,
            metadata=metadata,
            client_id=config["client_id"],
            nonce_hash=transaction["nonce_hash"],
        )
        email = str(
            claims.get("email")
            or claims.get("preferred_username")
            or claims.get("upn")
            or ""
        ).strip().lower()
        if not email or "@" not in email:
            raise ValueError("OIDC provider did not return a usable email")
        if claims.get("email_verified") is False:
            raise ValueError("OIDC email is not verified")
        domain = self.email_domain(email)
        if domain not in config["email_domains"]:
            raise ValueError("OIDC email domain is not allowed")

        issuer = str(claims["iss"])
        subject = str(claims["sub"])
        identity = self._repository.find_identity(
            owner_id=config["owner_id"],
            issuer=issuer,
            subject=subject,
        )

        if identity is not None:
            user = self._account_repository.get_user(identity["user_id"])
            try:
                membership = self._account_repository.get_membership(
                    user_id=user["id"],
                    owner_id=config["owner_id"],
                )
            except KeyError:
                raise ValueError("SSO identity no longer has workspace access") from None
            self._repository.touch_identity(
                identity_id=identity["id"],
                email=email,
            )
        else:
            user = self._account_repository.find_user_by_email(email)
            if user is not None:
                try:
                    membership = self._account_repository.get_membership(
                        user_id=user["id"],
                        owner_id=config["owner_id"],
                    )
                except KeyError:
                    if not config["auto_join"]:
                        raise ValueError("account is not a member of this workspace") from None
                    membership = self._account_repository.create_membership(
                        owner_id=config["owner_id"],
                        user_id=user["id"],
                        role="viewer",
                    )
            else:
                if not config["auto_join"]:
                    raise ValueError("account is not provisioned for this workspace")
                display_name = str(
                    claims.get("name")
                    or claims.get("given_name")
                    or email.split("@", 1)[0]
                )
                user, membership = self._accounts.create_sso_account(
                    owner_id=config["owner_id"],
                    email=email,
                    display_name=display_name,
                )
            self._repository.bind_identity(
                owner_id=config["owner_id"],
                user_id=user["id"],
                issuer=issuer,
                subject=subject,
                email=email,
            )

        if user["email_verified_at"] is None:
            self._account_repository.mark_email_verified(user_id=user["id"])
        self._account_repository.record_login_success(
            user_id=user["id"],
            client_ip=client_ip,
        )
        if membership["role"] == "owner" and config["verified_at"] is None:
            config = self._repository.mark_verified(owner_id=config["owner_id"])

        amr = claims.get("amr") or []
        if isinstance(amr, str):
            amr = [amr]
        mfa_authenticated = any(
            str(item).lower() in {"mfa", "otp", "hwk", "swk", "fido"}
            for item in amr
        )
        self._account_repository.record_auth_event(
            email=email,
            event_type="sso_login_succeeded",
            success=True,
            user_id=user["id"],
            client_ip=client_ip,
            user_agent=user_agent,
            details={
                "owner_id": config["owner_id"],
                "provider_type": config["provider_type"],
                "idp_mfa": mfa_authenticated,
            },
        )
        session = self._accounts.issue_sso_session(
            user_id=user["id"],
            owner_id=config["owner_id"],
            mfa_authenticated=mfa_authenticated,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return SsoCompletion(
            session=session,
            email=email,
            workspace_id=config["owner_id"],
            provider_name=config["display_name"],
        )

    def success_redirect_url(self) -> str:
        return f"{self._public_web_url}/#/sso-complete"

    def failure_redirect_url(self) -> str:
        return f"{self._public_web_url}/#/login?sso=failed"

    def _discovery(self, config: dict) -> dict:
        issuer = self._validate_url(config["issuer_url"], allow_http_local=True)
        url = issuer + "/.well-known/openid-configuration"
        response = self._http.get(url, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise ValueError("OIDC discovery failed")
        metadata = response.json()
        discovered_issuer = str(metadata.get("issuer") or "").rstrip("/")
        if discovered_issuer != issuer:
            raise ValueError("OIDC discovery issuer mismatch")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            endpoint = metadata.get(key)
            if not isinstance(endpoint, str):
                raise ValueError(f"OIDC discovery missing {key}")
            self._validate_url(endpoint, allow_http_local=True)
        return metadata

    def _verify_id_token(
        self,
        *,
        id_token: str,
        metadata: dict,
        client_id: str,
        nonce_hash: str,
    ) -> dict:
        parts = id_token.split(".")
        if len(parts) != 3:
            raise ValueError("invalid OIDC ID token")
        try:
            header = json.loads(self._b64url_decode(parts[0]))
            claims = json.loads(self._b64url_decode(parts[1]))
            signature = self._b64url_decode(parts[2])
        except (ValueError, json.JSONDecodeError):
            raise ValueError("invalid OIDC ID token") from None

        if header.get("alg") != "RS256":
            raise ValueError("unsupported OIDC signing algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise ValueError("OIDC ID token is missing key ID")

        jwks_response = self._http.get(
            self._validate_url(metadata["jwks_uri"], allow_http_local=True),
            headers={"Accept": "application/json"},
        )
        if jwks_response.status_code >= 400:
            raise ValueError("OIDC signing keys could not be loaded")
        jwks = jwks_response.json()
        key = next(
            (
                item
                for item in jwks.get("keys", [])
                if item.get("kid") == kid and item.get("kty") == "RSA"
            ),
            None,
        )
        if key is None:
            raise ValueError("OIDC signing key not found")
        try:
            modulus = int.from_bytes(self._b64url_decode(key["n"]), "big")
            exponent = int.from_bytes(self._b64url_decode(key["e"]), "big")
            public_key = rsa.RSAPublicNumbers(exponent, modulus).public_key()
            public_key.verify(
                signature,
                f"{parts[0]}.{parts[1]}".encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except Exception:
            raise ValueError("OIDC ID token signature is invalid") from None

        now = int(datetime.now(UTC).timestamp())
        issuer = str(claims.get("iss") or "").rstrip("/")
        if issuer != str(metadata["issuer"]).rstrip("/"):
            raise ValueError("OIDC issuer mismatch")
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else list(audience or [])
        if client_id not in audiences:
            raise ValueError("OIDC audience mismatch")
        if len(audiences) > 1 and claims.get("azp") != client_id:
            raise ValueError("OIDC authorized party mismatch")
        try:
            if int(claims.get("exp", 0)) <= now:
                raise ValueError("OIDC ID token has expired")
            if int(claims.get("nbf", 0) or 0) > now + 60:
                raise ValueError("OIDC ID token is not active")
            if int(claims.get("iat", now) or now) > now + 60:
                raise ValueError("OIDC ID token issued-at time is invalid")
        except (TypeError, ValueError):
            raise ValueError("OIDC ID token time claims are invalid") from None

        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not secrets.compare_digest(
            self._hash(nonce),
            nonce_hash,
        ):
            raise ValueError("OIDC nonce mismatch")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise ValueError("OIDC ID token is missing subject")
        return claims

    def _encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("SSO secret cannot be decrypted") from exc
