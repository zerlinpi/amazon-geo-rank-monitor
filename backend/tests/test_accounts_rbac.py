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
        allow_public_signup=True,
    )
    return TestClient(create_app(services)), services


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
        json={
            "email": "owner@example.com",
            "password": "correct-horse-battery",
            "display_name": "Owner",
            "workspace_name": "Acme",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_owner_registration_session_and_logout() -> None:
    client, _ = build_client()
    registered = register_owner(client)
    token = registered["session_token"]

    assert token.startswith("agrs_")
    assert registered["workspace"]["role"] == "owner"

    created = client.post(
        "/api/v1/geo-profiles",
        headers=bearer(token),
        json=geo_payload(),
    )
    assert created.status_code == 201

    me = client.get("/api/v1/auth/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "owner@example.com"
    assert me.json()["workspace"]["name"] == "Acme"

    logout = client.post("/api/v1/auth/logout", headers=bearer(token))
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401


def test_login_returns_new_human_session() -> None:
    client, _ = build_client()
    register_owner(client)

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "OWNER@example.com",
            "password": "correct-horse-battery",
        },
    )

    assert login.status_code == 200
    assert login.json()["session_token"].startswith("agrs_")
    assert login.json()["workspace"]["role"] == "owner"


def test_invited_viewer_can_read_but_cannot_write() -> None:
    client, _ = build_client()
    owner = register_owner(client)
    owner_headers = bearer(owner["session_token"])

    invitation = client.post(
        "/api/v1/team/invitations",
        headers=owner_headers,
        json={"email": "viewer@example.com", "role": "viewer"},
    )
    assert invitation.status_code == 201
    invite_token = invitation.json()["invitation_token"]
    assert invite_token.startswith("agri_")

    viewer = client.post(
        "/api/v1/auth/register",
        json={
            "email": "viewer@example.com",
            "password": "viewer-secure-password",
            "display_name": "Viewer",
            "invitation_token": invite_token,
        },
    )
    assert viewer.status_code == 201
    viewer_headers = bearer(viewer.json()["session_token"])
    assert viewer.json()["workspace"]["role"] == "viewer"

    assert client.get(
        "/api/v1/geo-profiles",
        headers=viewer_headers,
    ).status_code == 200

    denied = client.post(
        "/api/v1/geo-profiles",
        headers=viewer_headers,
        json=geo_payload(),
    )
    assert denied.status_code == 403
    assert "geo:write" in denied.json()["detail"]


def test_owner_can_promote_member_and_last_owner_is_protected() -> None:
    client, _ = build_client()
    owner = register_owner(client)
    owner_headers = bearer(owner["session_token"])

    invitation = client.post(
        "/api/v1/team/invitations",
        headers=owner_headers,
        json={"email": "analyst@example.com", "role": "analyst"},
    ).json()
    analyst = client.post(
        "/api/v1/auth/register",
        json={
            "email": "analyst@example.com",
            "password": "analyst-secure-pass",
            "display_name": "Analyst",
            "invitation_token": invitation["invitation_token"],
        },
    ).json()

    members = client.get("/api/v1/team/members", headers=owner_headers).json()
    analyst_member = next(
        item for item in members if item["email"] == "analyst@example.com"
    )
    owner_member = next(
        item for item in members if item["email"] == "owner@example.com"
    )

    promoted = client.patch(
        f"/api/v1/team/members/{analyst_member['user_id']}",
        headers=owner_headers,
        json={"role": "admin"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    protected = client.patch(
        f"/api/v1/team/members/{owner_member['user_id']}",
        headers=owner_headers,
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
    assert response.json()["workspace"]["id"] == tenant["id"]
    assert response.json()["workspace"]["role"] == "owner"
    session_token = response.json()["session_token"]
    assert client.get(
        "/api/v1/auth/me",
        headers=bearer(session_token),
    ).status_code == 200
