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


def build_client(*, auth_rate_limit: int = 20):
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
        session_ttl_hours=24,
        invitation_ttl_hours=24,
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
        auto_strict_runtime_policy={
            "enabled": True,
            "min_confidence": 0.75,
            "max_upstream_probes_per_run": 3,
        },
        allow_public_signup=True,
    )
    return client_for(services, auth_rate_limit=auth_rate_limit), services


def client_for(services, *, auth_rate_limit: int = 20) -> TestClient:
    return TestClient(
        create_app(
            services,
            auth_rate_limit_per_minute=auth_rate_limit,
        )
    )


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("agrm_csrf")
    assert token
    return {"X-CSRF-Token": token}


def geo_payload():
    return {
        "id": "ny",
        "name": "New York",
        "marketplace": "amazon.com",
        "ip_country": "US",
        "delivery_country": "US",
        "delivery_postal_code": "10001",
        "device": "desktop",
        "weight": "100",
        "enabled": True,
    }


def register_owner(client: TestClient):
    response = client.post(
        "/api/v1/auth/register",
        headers={"User-Agent": "owner-browser/1.0"},
        json={
            "email": "owner@example.com",
            "password": "correct-horse-battery",
            "display_name": "Owner",
            "workspace_name": "Acme",
        },
    )
    assert response.status_code == 201
    assert "session_token" not in response.json()
    assert client.cookies.get("agrm_session", "").startswith("agrs_")
    assert client.cookies.get("agrm_csrf", "").startswith("agrc_")
    return response.json()


def test_owner_registration_cookie_csrf_and_logout() -> None:
    client, _ = build_client()
    registered = register_owner(client)

    assert registered["workspace"]["role"] == "owner"

    denied = client.post("/api/v1/geo-profiles", json=geo_payload())
    assert denied.status_code == 403
    assert "CSRF" in denied.json()["detail"]

    created = client.post(
        "/api/v1/geo-profiles",
        headers=csrf_headers(client),
        json=geo_payload(),
    )
    assert created.status_code == 201

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "owner@example.com"
    assert me.json()["workspace"]["name"] == "Acme"

    logout = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_owner_can_manage_workspace_verification_defaults() -> None:
    client, services = build_client()
    registered = register_owner(client)
    owner_id = registered["workspace"]["id"]

    current = client.get("/api/v1/team/verification-policy")
    assert current.status_code == 200
    assert current.json()["enabled"] is None
    assert current.json()["effective"] == {
        "enabled": True,
        "min_confidence": 0.75,
        "max_upstream_probes_per_run": 3,
    }

    updated = client.patch(
        "/api/v1/team/verification-policy",
        headers=csrf_headers(client),
        json={
            "enabled": False,
            "min_confidence": 0.9,
            "max_upstream_probes_per_run": 1,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["effective"] == {
        "enabled": False,
        "min_confidence": 0.9,
        "max_upstream_probes_per_run": 1,
    }
    stored = services.tenant_repository.get_workspace_verification_policy(
        owner_id=owner_id
    )
    assert stored["enabled"] is False
    assert str(stored["min_confidence"]) == "0.9000"
    assert stored["max_upstream_probes_per_run"] == 1


def test_login_returns_cookie_without_exposing_session_token() -> None:
    client, _ = build_client()
    register_owner(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    login = client.post(
        "/api/v1/auth/login",
        headers={"User-Agent": "second-browser/2.0"},
        json={
            "email": "OWNER@example.com",
            "password": "correct-horse-battery",
        },
    )

    assert login.status_code == 200
    assert "session_token" not in login.json()
    assert client.cookies.get("agrm_session", "").startswith("agrs_")
    assert login.json()["workspace"]["role"] == "owner"


def test_invited_viewer_can_read_but_cannot_write() -> None:
    owner_client, services = build_client()
    register_owner(owner_client)

    invitation = owner_client.post(
        "/api/v1/team/invitations",
        headers=csrf_headers(owner_client),
        json={"email": "viewer@example.com", "role": "viewer"},
    )
    assert invitation.status_code == 201
    invite_token = invitation.json()["invitation_token"]

    viewer_client = client_for(services)
    viewer = viewer_client.post(
        "/api/v1/auth/register",
        json={
            "email": "viewer@example.com",
            "password": "viewer-secure-password",
            "display_name": "Viewer",
            "invitation_token": invite_token,
        },
    )
    assert viewer.status_code == 201
    assert viewer.json()["workspace"]["role"] == "viewer"

    assert viewer_client.get("/api/v1/geo-profiles").status_code == 200

    denied = viewer_client.post(
        "/api/v1/geo-profiles",
        headers=csrf_headers(viewer_client),
        json=geo_payload(),
    )
    assert denied.status_code == 403
    assert "geo:write" in denied.json()["detail"]


def test_owner_can_promote_member_and_last_owner_is_protected() -> None:
    owner_client, services = build_client()
    register_owner(owner_client)

    invitation = owner_client.post(
        "/api/v1/team/invitations",
        headers=csrf_headers(owner_client),
        json={"email": "analyst@example.com", "role": "analyst"},
    ).json()
    analyst_client = client_for(services)
    analyst = analyst_client.post(
        "/api/v1/auth/register",
        json={
            "email": "analyst@example.com",
            "password": "analyst-secure-pass",
            "display_name": "Analyst",
            "invitation_token": invitation["invitation_token"],
        },
    ).json()

    members = owner_client.get("/api/v1/team/members").json()
    analyst_member = next(
        item for item in members if item["email"] == "analyst@example.com"
    )
    owner_member = next(
        item for item in members if item["email"] == "owner@example.com"
    )

    promoted = owner_client.patch(
        f"/api/v1/team/members/{analyst_member['user_id']}",
        headers=csrf_headers(owner_client),
        json={"role": "admin"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    protected = owner_client.patch(
        f"/api/v1/team/members/{owner_member['user_id']}",
        headers=csrf_headers(owner_client),
        json={"role": "viewer"},
    )
    assert protected.status_code == 409
    assert "at least one owner" in protected.json()["detail"]
    assert analyst["workspace"]["role"] == "analyst"


def test_existing_api_key_workspace_can_bootstrap_first_human_owner() -> None:
    client, services = build_client()
    tenant = services.tenant_repository.create_tenant("Legacy Workspace")
    key = services.api_keys.create(owner_id=tenant["id"], name="bootstrap")

    response = client.post(
        "/api/v1/team/bootstrap-owner",
        headers={"X-API-Key": key.plaintext},
        json={
            "email": "legacy-owner@example.com",
            "password": "legacy-owner-password",
            "display_name": "Legacy Owner",
        },
    )

    assert response.status_code == 201
    assert "session_token" not in response.json()
    assert response.json()["workspace"]["id"] == tenant["id"]
    assert response.json()["workspace"]["role"] == "owner"
    assert client.get("/api/v1/auth/me").status_code == 200

    member = services.account_repository.list_members(owner_id=tenant["id"])[0]
    machine_mutation = client.patch(
        f"/api/v1/team/members/{member['user_id']}",
        headers={"X-API-Key": key.plaintext},
        json={"role": "viewer"},
    )
    assert machine_mutation.status_code == 403
    assert "human session required" in machine_mutation.json()["detail"]


def test_public_login_is_rate_limited_by_client_ip() -> None:
    client, _ = build_client(auth_rate_limit=2)

    for _ in range(2):
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "missing@example.com",
                "password": "not-the-password",
            },
        )
        assert response.status_code == 401

    limited = client.post(
        "/api/v1/auth/login",
        json={
            "email": "missing@example.com",
            "password": "not-the-password",
        },
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


def test_human_cookie_requests_are_audited_as_user_actor() -> None:
    client, services = build_client()
    registered = register_owner(client)

    response = client.get(
        "/api/v1/auth/me",
        headers={"X-Request-ID": "human-audit-1"},
    )
    assert response.status_code == 200

    events = services.audit_repository.list(owner_id=registered["workspace"]["id"])
    event = next(item for item in events if item["request_id"] == "human-audit-1")
    assert event["actor_type"] == "session"
    assert event["user_id"] == registered["user"]["id"]
    assert event["api_key_id"] is None


def test_remote_session_revoke_invalidates_other_device() -> None:
    first, services = build_client()
    register_owner(first)

    second = client_for(services)
    login = second.post(
        "/api/v1/auth/login",
        headers={"User-Agent": "remote-device/1.0"},
        json={
            "email": "owner@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert login.status_code == 200

    sessions = first.get("/api/v1/auth/sessions").json()
    remote = next(item for item in sessions if not item["current"])
    assert remote["user_agent"] == "remote-device/1.0"

    revoked = first.delete(
        f"/api/v1/auth/sessions/{remote['id']}",
        headers=csrf_headers(first),
    )
    assert revoked.status_code == 204
    assert second.get("/api/v1/auth/me").status_code == 401
    assert first.get("/api/v1/auth/me").status_code == 200


def test_password_change_revokes_other_sessions_and_keeps_current() -> None:
    first, services = build_client()
    register_owner(first)

    second = client_for(services)
    assert second.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": "correct-horse-battery",
        },
    ).status_code == 200

    changed = first.post(
        "/api/v1/auth/change-password",
        headers=csrf_headers(first),
        json={
            "current_password": "correct-horse-battery",
            "new_password": "new-correct-horse-battery",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["revoked_other_sessions"] == 1
    assert first.get("/api/v1/auth/me").status_code == 200
    assert second.get("/api/v1/auth/me").status_code == 401

    fresh = client_for(services)
    assert fresh.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": "correct-horse-battery",
        },
    ).status_code == 401
    assert fresh.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": "new-correct-horse-battery",
        },
    ).status_code == 200
