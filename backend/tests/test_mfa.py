import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.accounts import AccountService
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.domain.models import SerpResult
from amazon_geo_rank_monitor.repositories.account_repository import AccountRepository
from amazon_geo_rank_monitor.repositories.audit_repository import AuditRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository


class FakeProvider:
    provider_name = "fake"

    async def search(self, **kwargs):
        return SerpResult()


def build_client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    account_repository = AccountRepository(engine)
    accounts = AccountService(
        repository=account_repository,
        mfa_encryption_key="test-mfa-encryption-key",
        mfa_challenge_minutes=5,
        trusted_device_days=30,
    )
    services = AppServices(
        tenant_repository=tenants,
        geo_repository=GeoRepository(engine),
        monitor_repository=MonitorRepository(engine),
        job_repository=JobRepository(engine),
        rank_repository=RankRepository(engine),
        api_keys=ApiKeyService(repository=tenants, pepper="pepper"),
        provider_registry=ProviderRegistry(
            managed=FakeProvider(),
            strict=FakeProvider(),
        ),
        database_engine=engine,
        audit_repository=AuditRepository(engine),
        account_repository=account_repository,
        accounts=accounts,
        allow_public_signup=True,
    )
    return TestClient(create_app(services)), services


def client_for(services) -> TestClient:
    return TestClient(create_app(services))


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("agrm_csrf")
    assert token
    return {"X-CSRF-Token": token}


def register_owner(client: TestClient):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "password": "correct-horse-battery",
            "display_name": "Owner",
            "workspace_name": "Acme",
        },
    )
    assert response.status_code == 201
    return response.json()


def enable_mfa(client: TestClient, services) -> list[str]:
    user = services.account_repository.find_user_by_email("owner@example.com")
    services.account_repository.mark_email_verified(user_id=user["id"])

    enrollment = client.post(
        "/api/v1/auth/mfa/enroll",
        headers=csrf_headers(client),
    )
    assert enrollment.status_code == 200
    secret = enrollment.json()["secret"]
    code = pyotp.TOTP(secret).now()

    confirmed = client.post(
        "/api/v1/auth/mfa/enroll/verify",
        headers=csrf_headers(client),
        json={"code": code},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["enabled"] is True
    codes = confirmed.json()["recovery_codes"]
    assert len(codes) == 10
    return codes


def logout(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/logout",
        headers=csrf_headers(client),
    )
    assert response.status_code == 204


def start_mfa_login(client: TestClient, password: str = "correct-horse-battery"):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": password,
        },
    )
    assert response.status_code == 202
    body = response.json()
    assert body["mfa_required"] is True
    assert body["challenge_token"].startswith("agrmfa_")
    assert not client.cookies.get("agrm_session")
    return body


def test_totp_enrollment_and_two_stage_login() -> None:
    client, services = build_client()
    register_owner(client)
    enable_mfa(client, services)

    profile = client.get("/api/v1/auth/me").json()
    assert profile["user"]["mfa_enabled"] is True
    assert profile["user"]["mfa_authenticated"] is True
    assert profile["user"]["recovery_codes_remaining"] == 10

    user = services.account_repository.find_user_by_email("owner@example.com")
    secret = services.accounts._mfa.decrypt_secret(user["mfa_secret_encrypted"])

    logout(client)
    challenge = start_mfa_login(client)
    completed = client.post(
        "/api/v1/auth/mfa/complete",
        json={
            "challenge_token": challenge["challenge_token"],
            "code": pyotp.TOTP(secret).now(),
            "remember_device": False,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["mfa_required"] is False
    assert client.cookies.get("agrm_session", "").startswith("agrs_")
    assert client.get("/api/v1/auth/me").json()["user"]["mfa_authenticated"] is True


def test_recovery_code_is_single_use() -> None:
    client, services = build_client()
    register_owner(client)
    recovery_codes = enable_mfa(client, services)
    first_code = recovery_codes[0]

    logout(client)
    challenge = start_mfa_login(client)
    completed = client.post(
        "/api/v1/auth/mfa/complete",
        json={
            "challenge_token": challenge["challenge_token"],
            "code": first_code,
            "remember_device": False,
        },
    )
    assert completed.status_code == 200

    logout(client)
    next_challenge = start_mfa_login(client)
    reused = client.post(
        "/api/v1/auth/mfa/complete",
        json={
            "challenge_token": next_challenge["challenge_token"],
            "code": first_code,
            "remember_device": False,
        },
    )
    assert reused.status_code == 422


def test_trusted_device_skips_next_mfa_challenge() -> None:
    client, services = build_client()
    register_owner(client)
    enable_mfa(client, services)
    user = services.account_repository.find_user_by_email("owner@example.com")
    secret = services.accounts._mfa.decrypt_secret(user["mfa_secret_encrypted"])

    logout(client)
    challenge = start_mfa_login(client)
    completed = client.post(
        "/api/v1/auth/mfa/complete",
        json={
            "challenge_token": challenge["challenge_token"],
            "code": pyotp.TOTP(secret).now(),
            "remember_device": True,
        },
    )
    assert completed.status_code == 200
    assert client.cookies.get("agrm_trusted_device", "").startswith("agrd_")

    logout(client)
    trusted_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert trusted_login.status_code == 200
    assert trusted_login.json()["mfa_required"] is False
    assert trusted_login.json()["user"]["mfa_authenticated"] is True


def test_workspace_policy_blocks_member_until_mfa_is_enabled() -> None:
    owner, services = build_client()
    register_owner(owner)
    enable_mfa(owner, services)

    policy = owner.patch(
        "/api/v1/team/security-policy",
        headers=csrf_headers(owner),
        json={"require_mfa": True},
    )
    assert policy.status_code == 200
    assert policy.json()["require_mfa"] is True

    invitation = owner.post(
        "/api/v1/team/invitations",
        headers=csrf_headers(owner),
        json={"email": "viewer@example.com", "role": "viewer"},
    )
    assert invitation.status_code == 201

    viewer = client_for(services)
    registered = viewer.post(
        "/api/v1/auth/register",
        json={
            "email": "viewer@example.com",
            "password": "viewer-secure-password",
            "display_name": "Viewer",
            "invitation_token": invitation.json()["invitation_token"],
        },
    )
    assert registered.status_code == 201
    assert registered.json()["workspace"]["mfa_setup_required"] is True

    blocked = viewer.get("/api/v1/geo-profiles")
    assert blocked.status_code == 403
    assert "MFA required" in blocked.json()["detail"]

    enrollment = viewer.post(
        "/api/v1/auth/mfa/enroll",
        headers=csrf_headers(viewer),
    )
    assert enrollment.status_code == 200
    confirmed = viewer.post(
        "/api/v1/auth/mfa/enroll/verify",
        headers=csrf_headers(viewer),
        json={"code": pyotp.TOTP(enrollment.json()["secret"]).now()},
    )
    assert confirmed.status_code == 200
    assert viewer.get("/api/v1/geo-profiles").status_code == 200


def test_workspace_policy_requires_all_existing_members_to_have_mfa() -> None:
    owner, services = build_client()
    register_owner(owner)
    enable_mfa(owner, services)

    invitation = owner.post(
        "/api/v1/team/invitations",
        headers=csrf_headers(owner),
        json={"email": "viewer@example.com", "role": "viewer"},
    ).json()
    viewer = client_for(services)
    assert viewer.post(
        "/api/v1/auth/register",
        json={
            "email": "viewer@example.com",
            "password": "viewer-secure-password",
            "display_name": "Viewer",
            "invitation_token": invitation["invitation_token"],
        },
    ).status_code == 201

    denied = owner.patch(
        "/api/v1/team/security-policy",
        headers=csrf_headers(owner),
        json={"require_mfa": True},
    )
    assert denied.status_code == 409
    assert "must enable MFA first" in denied.json()["detail"]


def test_mfa_cannot_be_disabled_while_workspace_requires_it() -> None:
    client, services = build_client()
    register_owner(client)
    enable_mfa(client, services)
    user = services.account_repository.find_user_by_email("owner@example.com")
    secret = services.accounts._mfa.decrypt_secret(user["mfa_secret_encrypted"])

    assert client.patch(
        "/api/v1/team/security-policy",
        headers=csrf_headers(client),
        json={"require_mfa": True},
    ).status_code == 200

    disabled = client.post(
        "/api/v1/auth/mfa/disable",
        headers=csrf_headers(client),
        json={
            "current_password": "correct-horse-battery",
            "code": pyotp.TOTP(secret).now(),
        },
    )
    assert disabled.status_code == 422
    assert "workspace MFA policy" in disabled.json()["detail"]


def test_workspace_mfa_policy_does_not_block_api_keys() -> None:
    client, services = build_client()
    registered = register_owner(client)
    enable_mfa(client, services)

    policy = client.patch(
        "/api/v1/team/security-policy",
        headers=csrf_headers(client),
        json={"require_mfa": True},
    )
    assert policy.status_code == 200

    key = services.api_keys.create(
        owner_id=registered["workspace"]["id"],
        name="automation",
    )
    machine = client_for(services)
    response = machine.get(
        "/api/v1/geo-profiles",
        headers={"X-API-Key": key.plaintext},
    )
    assert response.status_code == 200
