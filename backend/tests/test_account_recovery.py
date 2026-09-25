import re

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.accounts import AccountService
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.domain.models import SerpResult
from amazon_geo_rank_monitor.notifications.email import MemoryEmailSender
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


def build_client(*, login_max_failures: int = 3, login_lock_minutes: int = 15):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    account_repository = AccountRepository(engine)
    mailer = MemoryEmailSender()
    accounts = AccountService(
        repository=account_repository,
        session_ttl_hours=24,
        invitation_ttl_hours=24,
        verification_ttl_hours=24,
        password_reset_ttl_minutes=30,
        login_max_failures=login_max_failures,
        login_lock_minutes=login_lock_minutes,
        email_sender=mailer,
        public_web_url="http://frontend.test",
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
    return TestClient(create_app(services)), services, mailer


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("agrm_csrf")
    assert token
    return {"X-CSRF-Token": token}


def register(client: TestClient, *, email: str = "owner@example.com"):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery",
            "display_name": "Owner",
            "workspace_name": "Acme",
        },
    )
    assert response.status_code == 201
    return response.json()


def token_from_mail(text: str, prefix: str) -> str:
    match = re.search(rf"({prefix}_[A-Za-z0-9_-]+)", text)
    assert match
    return match.group(1)


def test_new_registration_sends_single_use_email_verification() -> None:
    client, _, mailer = build_client()
    registered = register(client)

    assert registered["user"]["email_verified"] is False
    assert len(mailer.messages) == 1
    token = token_from_mail(mailer.messages[0].text, "agrv")

    verified = client.post(
        "/api/v1/auth/verify-email",
        json={"token": token},
    )
    assert verified.status_code == 200
    assert verified.json()["verified"] is True

    profile = client.get("/api/v1/auth/me")
    assert profile.status_code == 200
    assert profile.json()["user"]["email_verified"] is True

    reused = client.post(
        "/api/v1/auth/verify-email",
        json={"token": token},
    )
    assert reused.status_code == 422


def test_resend_verification_invalidates_previous_token() -> None:
    client, _, mailer = build_client()
    register(client)
    first = token_from_mail(mailer.messages[-1].text, "agrv")

    resent = client.post(
        "/api/v1/auth/resend-verification",
        headers=csrf_headers(client),
    )
    assert resent.status_code == 200
    assert resent.json()["sent"] is True
    second = token_from_mail(mailer.messages[-1].text, "agrv")
    assert second != first

    assert client.post(
        "/api/v1/auth/verify-email",
        json={"token": first},
    ).status_code == 422
    assert client.post(
        "/api/v1/auth/verify-email",
        json={"token": second},
    ).status_code == 200


def test_forgot_password_does_not_reveal_account_existence() -> None:
    client, _, mailer = build_client()
    register(client)
    initial_messages = len(mailer.messages)

    existing = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "owner@example.com"},
    )
    missing = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "missing@example.com"},
    )

    assert existing.status_code == 202
    assert missing.status_code == 202
    assert existing.json() == missing.json()
    assert len(mailer.messages) == initial_messages + 1
    assert "agrr_" in mailer.messages[-1].text


def test_password_reset_is_single_use_revokes_sessions_and_unlocks_account() -> None:
    client, services, mailer = build_client(login_max_failures=2)
    register(client)

    second = TestClient(client.app)
    assert second.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": "correct-horse-battery",
        },
    ).status_code == 200

    for _ in range(2):
        locked = TestClient(client.app).post(
            "/api/v1/auth/login",
            json={
                "email": "owner@example.com",
                "password": "wrong-password",
            },
        )
    assert locked.status_code == 423

    requested = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "owner@example.com"},
    )
    assert requested.status_code == 202
    token = token_from_mail(mailer.messages[-1].text, "agrr")

    reset = client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "new_password": "new-correct-horse-battery",
        },
    )
    assert reset.status_code == 200
    assert reset.json()["revoked_sessions"] >= 2
    assert client.get("/api/v1/auth/me").status_code == 401
    assert second.get("/api/v1/auth/me").status_code == 401

    reused = client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "new_password": "another-secure-password",
        },
    )
    assert reused.status_code == 422

    fresh = TestClient(client.app)
    login = fresh.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": "new-correct-horse-battery",
        },
    )
    assert login.status_code == 200

    user = services.account_repository.find_user_by_email("owner@example.com")
    assert user["failed_login_count"] == 0
    assert user["locked_until"] is None


def test_login_lockout_and_security_events_are_user_scoped() -> None:
    client, services, _ = build_client(login_max_failures=2)
    first = register(client, email="owner@example.com")

    other = TestClient(client.app)
    register(other, email="other@example.com")

    bad = TestClient(client.app)
    assert bad.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "bad-password"},
    ).status_code == 401
    locked = bad.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "bad-password"},
    )
    assert locked.status_code == 423

    events = client.get("/api/v1/auth/security-events")
    assert events.status_code == 200
    body = events.json()
    assert any(item["event_type"] == "login_locked" for item in body)
    assert all(item["email"] == "owner@example.com" for item in body)
    assert all(item["user_id"] == first["user"]["id"] for item in body)

    other_user = services.account_repository.find_user_by_email("other@example.com")
    assert all(item["user_id"] != other_user["id"] for item in body)
