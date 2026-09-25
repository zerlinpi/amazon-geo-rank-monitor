import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.routes.team import update_sso_enforcement
from amazon_geo_rank_monitor.api.schemas import WorkspaceSsoEnforcementUpdate
from amazon_geo_rank_monitor.auth.accounts import AccountService, SsoRequiredError
from amazon_geo_rank_monitor.auth.api_keys import ApiPrincipal
from amazon_geo_rank_monitor.auth.sso import OidcSsoService
from amazon_geo_rank_monitor.repositories.account_repository import AccountRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.sso_repository import SsoRepository

ISSUER = "https://idp.example.test"
CLIENT_ID = "agrm-client"
CLIENT_SECRET = "super-secret"


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class FakeOidcProvider:
    def __init__(self) -> None:
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self.nonce = ""
        self.email = "owner@example.com"
        self.subject = "subject-owner"
        self.amr: list[str] = ["pwd"]
        self.tamper_signature = False

    @property
    def jwk(self) -> dict:
        numbers = self.private_key.public_key().public_numbers()
        return {
            "kty": "RSA",
            "kid": "test-key",
            "alg": "RS256",
            "use": "sig",
            "n": b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
            "e": b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
        }

    def id_token(self) -> str:
        now = int(datetime.now(UTC).timestamp())
        header = {"alg": "RS256", "kid": "test-key", "typ": "JWT"}
        claims = {
            "iss": ISSUER,
            "sub": self.subject,
            "aud": CLIENT_ID,
            "exp": now + 300,
            "iat": now,
            "nonce": self.nonce,
            "email": self.email,
            "email_verified": True,
            "name": "SSO User",
            "amr": self.amr,
        }
        encoded_header = b64url(
            json.dumps(header, separators=(",", ":")).encode()
        )
        encoded_claims = b64url(
            json.dumps(claims, separators=(",", ":")).encode()
        )
        signing_input = f"{encoded_header}.{encoded_claims}".encode()
        signature = self.private_key.sign(
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        if self.tamper_signature:
            signature = b"x" + signature[1:]
        return f"{encoded_header}.{encoded_claims}.{b64url(signature)}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [self.jwk]})
        if request.url.path == "/token":
            form = dict(
                pair.split("=", 1)
                for pair in request.content.decode().split("&")
                if "=" in pair
            )
            assert form["client_id"] == CLIENT_ID
            return httpx.Response(200, json={"id_token": self.id_token()})
        raise AssertionError(f"unexpected OIDC request: {request.url}")


def build_services():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    accounts_repository = AccountRepository(engine)
    sso_repository = SsoRepository(engine)
    accounts = AccountService(
        repository=accounts_repository,
        sso_repository=sso_repository,
        mfa_encryption_key="mfa-test-key",
    )
    provider = FakeOidcProvider()
    http_client = httpx.Client(
        transport=httpx.MockTransport(provider.handler),
    )
    sso = OidcSsoService(
        repository=sso_repository,
        account_repository=accounts_repository,
        accounts=accounts,
        encryption_key="sso-test-key",
        callback_url="http://localhost:8000/api/v1/auth/sso/callback",
        public_web_url="http://localhost:5173",
        http_client=http_client,
    )
    return accounts_repository, sso_repository, accounts, sso, provider


def register_owner(accounts: AccountService):
    created = accounts.register(
        email="owner@example.com",
        password="correct-horse-battery",
        display_name="Owner",
        workspace_name="Acme",
    )
    return created


def configure_owner_sso(sso: OidcSsoService, owner_id: str, *, auto_join: bool = False):
    config = sso.configure(
        owner_id=owner_id,
        provider_type="oidc",
        display_name="Acme SSO",
        issuer_url=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        email_domains=["example.com"],
        auto_join=auto_join,
        enabled=True,
    )
    assert "client_secret_encrypted" not in config
    assert config["verified_at"] is None
    return config


def start_and_capture_nonce(
    sso: OidcSsoService,
    provider: FakeOidcProvider,
    *,
    owner_id: str,
    email: str,
):
    started = sso.start_login(owner_id=owner_id, email_hint=email)
    parsed = urlparse(started.authorization_url)
    query = parse_qs(parsed.query)
    provider.nonce = query["nonce"][0]
    assert query["state"][0].startswith("agrsso_")
    assert query["code_challenge_method"] == ["S256"]
    return query["state"][0]


def test_owner_sso_verifies_config_and_enforcement_blocks_password_login() -> None:
    _, sso_repository, accounts, sso, provider = build_services()
    owner_session = register_owner(accounts)
    owner_id = owner_session.principal.owner_id
    configure_owner_sso(sso, owner_id)

    with pytest.raises(ValueError, match="enabled and verified"):
        sso.set_enforcement(owner_id=owner_id, enforce_sso=True)

    state = start_and_capture_nonce(
        sso,
        provider,
        owner_id=owner_id,
        email="owner@example.com",
    )
    completion = sso.complete_login(
        state=state,
        code="authorization-code",
        client_ip="127.0.0.1",
        user_agent="test-browser",
    )
    assert completion.workspace_id == owner_id
    assert completion.session.principal.email == "owner@example.com"
    assert completion.session.principal.auth_method == "sso"
    assert completion.session.principal.sso_owner_id == owner_id
    assert sso_repository.get_config(owner_id=owner_id)["verified_at"] is not None

    enforced = sso.set_enforcement(owner_id=owner_id, enforce_sso=True)
    assert enforced["enforce_sso"] is True

    with pytest.raises(SsoRequiredError, match="SSO is required"):
        accounts.login(
            email="owner@example.com",
            password="correct-horse-battery",
            workspace_id=owner_id,
        )


def test_sso_state_is_single_use_and_nonce_is_required() -> None:
    _, _, accounts, sso, provider = build_services()
    owner_id = register_owner(accounts).principal.owner_id
    configure_owner_sso(sso, owner_id)
    state = start_and_capture_nonce(
        sso,
        provider,
        owner_id=owner_id,
        email="owner@example.com",
    )

    provider.nonce = "wrong-nonce"
    with pytest.raises(ValueError, match="nonce mismatch"):
        sso.complete_login(state=state, code="authorization-code")

    provider.nonce = "unused"
    with pytest.raises(ValueError, match="invalid or expired SSO transaction"):
        sso.complete_login(state=state, code="authorization-code")


def test_sso_rejects_invalid_signature_and_disallowed_domain() -> None:
    _, _, accounts, sso, provider = build_services()
    owner_id = register_owner(accounts).principal.owner_id
    configure_owner_sso(sso, owner_id)

    state = start_and_capture_nonce(
        sso,
        provider,
        owner_id=owner_id,
        email="owner@example.com",
    )
    provider.tamper_signature = True
    with pytest.raises(ValueError, match="signature is invalid"):
        sso.complete_login(state=state, code="authorization-code")

    provider.tamper_signature = False
    provider.email = "owner@evil.example"
    state = start_and_capture_nonce(
        sso,
        provider,
        owner_id=owner_id,
        email="owner@example.com",
    )
    with pytest.raises(ValueError, match="domain is not allowed"):
        sso.complete_login(state=state, code="authorization-code")


def test_sso_auto_join_creates_viewer_and_binds_subject() -> None:
    accounts_repository, sso_repository, accounts, sso, provider = build_services()
    owner_id = register_owner(accounts).principal.owner_id
    configure_owner_sso(sso, owner_id, auto_join=True)

    provider.email = "viewer@example.com"
    provider.subject = "subject-viewer"
    state = start_and_capture_nonce(
        sso,
        provider,
        owner_id=owner_id,
        email="viewer@example.com",
    )
    completion = sso.complete_login(state=state, code="authorization-code")

    viewer = accounts_repository.find_user_by_email("viewer@example.com")
    assert viewer is not None
    membership = accounts_repository.get_membership(
        user_id=viewer["id"],
        owner_id=owner_id,
    )
    assert membership["role"] == "viewer"
    identity = sso_repository.find_identity(
        owner_id=owner_id,
        issuer=ISSUER,
        subject="subject-viewer",
    )
    assert identity["user_id"] == viewer["id"]
    assert completion.session.principal.user_id == viewer["id"]


def test_sso_without_auto_join_does_not_provision_unknown_user() -> None:
    accounts_repository, _, accounts, sso, provider = build_services()
    owner_id = register_owner(accounts).principal.owner_id
    configure_owner_sso(sso, owner_id, auto_join=False)

    provider.email = "missing@example.com"
    provider.subject = "subject-missing"
    state = start_and_capture_nonce(
        sso,
        provider,
        owner_id=owner_id,
        email="missing@example.com",
    )
    with pytest.raises(ValueError, match="not provisioned"):
        sso.complete_login(state=state, code="authorization-code")
    assert accounts_repository.find_user_by_email("missing@example.com") is None


def test_idp_mfa_claim_marks_sso_session_authenticated() -> None:
    _, _, accounts, sso, provider = build_services()
    owner_id = register_owner(accounts).principal.owner_id
    configure_owner_sso(sso, owner_id)
    provider.amr = ["pwd", "mfa"]

    state = start_and_capture_nonce(
        sso,
        provider,
        owner_id=owner_id,
        email="owner@example.com",
    )
    completion = sso.complete_login(state=state, code="authorization-code")
    assert completion.session.principal.mfa_authenticated_at is not None


def test_local_session_cannot_switch_into_enforced_sso_workspace() -> None:
    accounts_repository, sso_repository, accounts, sso, _ = build_services()
    local = register_owner(accounts)
    enterprise_owner = accounts.register(
        email="enterprise-owner@example.com",
        password="enterprise-owner-password",
        display_name="Enterprise Owner",
        workspace_name="Enterprise",
    )
    target_owner_id = enterprise_owner.principal.owner_id
    accounts_repository.create_membership(
        owner_id=target_owner_id,
        user_id=local.principal.user_id,
        role="viewer",
    )
    configure_owner_sso(sso, target_owner_id)
    sso_repository.mark_verified(owner_id=target_owner_id)
    sso.set_enforcement(owner_id=target_owner_id, enforce_sso=True)

    with pytest.raises(SsoRequiredError, match="SSO is required"):
        accounts.switch_workspace(
            principal=local.principal,
            owner_id=target_owner_id,
        )


def test_api_key_break_glass_can_only_disable_sso_enforcement() -> None:
    _, sso_repository, accounts, sso, _ = build_services()
    owner_id = register_owner(accounts).principal.owner_id
    configure_owner_sso(sso, owner_id)
    sso_repository.mark_verified(owner_id=owner_id)
    sso.set_enforcement(owner_id=owner_id, enforce_sso=True)

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                services=SimpleNamespace(sso=sso),
            )
        )
    )
    principal = ApiPrincipal(
        owner_id=owner_id,
        key_id="break-glass-key",
        scopes=frozenset({"team:manage"}),
    )

    disabled = update_sso_enforcement(
        WorkspaceSsoEnforcementUpdate(enforce_sso=False),
        request,
        principal,
    )
    assert disabled["enforce_sso"] is False

    with pytest.raises(HTTPException) as exc:
        update_sso_enforcement(
            WorkspaceSsoEnforcementUpdate(enforce_sso=True),
            request,
            principal,
        )
    assert exc.value.status_code == 403
    assert "only disable" in exc.value.detail
