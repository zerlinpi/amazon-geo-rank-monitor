from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.accounts import AccountService
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.auth.scim import ScimService
from amazon_geo_rank_monitor.domain.models import SerpResult
from amazon_geo_rank_monitor.repositories.account_repository import AccountRepository
from amazon_geo_rank_monitor.repositories.audit_repository import AuditRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.scim_repository import ScimRepository
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
    scim_repository = ScimRepository(engine)
    scim = ScimService(repository=scim_repository, pepper="scim-test-pepper")
    services = AppServices(
        tenant_repository=tenants,
        geo_repository=GeoRepository(engine),
        monitor_repository=MonitorRepository(engine),
        job_repository=JobRepository(engine),
        rank_repository=RankRepository(engine),
        api_keys=ApiKeyService(repository=tenants, pepper="api-test-pepper"),
        provider_registry=ProviderRegistry(
            managed=FakeProvider(),
            strict=FakeProvider(),
        ),
        database_engine=engine,
        audit_repository=AuditRepository(engine),
        account_repository=account_repository,
        accounts=accounts,
        scim_repository=scim_repository,
        scim=scim,
        allow_public_signup=True,
    )
    return TestClient(create_app(services)), services


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("agrm_csrf")
    assert token
    return {"X-CSRF-Token": token}


def register_owner(client: TestClient) -> dict:
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


def rotate_scim_token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/team/scim-token/rotate",
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    token = response.json()["token"]
    assert token.startswith("agrscim_")
    return token


def scim_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/scim+json",
    }


def create_scim_user(
    client: TestClient,
    token: str,
    *,
    email: str = "viewer@example.com",
    external_id: str = "idp-user-1",
) -> dict:
    response = client.post(
        "/scim/v2/Users",
        headers=scim_headers(token),
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": external_id,
            "userName": email,
            "displayName": "Provisioned Viewer",
            "active": True,
        },
    )
    assert response.status_code == 201
    assert response.headers["content-type"].startswith("application/scim+json")
    return response.json()


def test_scim_requires_bearer_and_exposes_provider_metadata() -> None:
    client, services = build_client()
    owner = register_owner(client)

    unauthorized = client.get("/scim/v2/ServiceProviderConfig")
    assert unauthorized.status_code == 401
    assert unauthorized.headers["content-type"].startswith(
        "application/scim+json"
    )
    assert unauthorized.json()["schemas"] == [
        "urn:ietf:params:scim:api:messages:2.0:Error"
    ]

    token = rotate_scim_token(client)
    response = client.get(
        "/scim/v2/ServiceProviderConfig",
        headers=scim_headers(token),
    )
    assert response.status_code == 200
    assert response.json()["patch"]["supported"] is True

    events = services.audit_repository.list(
        owner_id=owner["workspace"]["id"]
    )
    event = next(
        item
        for item in events
        if item["path"] == "/scim/v2/ServiceProviderConfig"
    )
    assert event["actor_type"] == "scim"


def test_scim_user_filter_suspend_revokes_workspace_session_and_reactivates() -> None:
    client, services = build_client()
    owner = register_owner(client)
    owner_id = owner["workspace"]["id"]
    token = rotate_scim_token(client)

    created = create_scim_user(client, token)
    membership_id = created["id"]
    assert created["active"] is True
    assert created["roles"][0]["value"] == "viewer"

    filtered = client.get(
        "/scim/v2/Users",
        headers=scim_headers(token),
        params={"filter": 'userName eq "viewer@example.com"'},
    )
    assert filtered.status_code == 200
    assert filtered.json()["totalResults"] == 1
    assert filtered.json()["Resources"][0]["id"] == membership_id

    user = services.account_repository.find_user_by_email("viewer@example.com")
    assert user is not None
    browser_session = services.accounts.issue_sso_session(
        user_id=user["id"],
        owner_id=owner_id,
        mfa_authenticated=False,
    )
    member_client = TestClient(client.app)
    member_client.cookies.set("agrm_session", browser_session.plaintext)
    assert member_client.get("/api/v1/auth/me").status_code == 200

    suspended = client.patch(
        f"/scim/v2/Users/{membership_id}",
        headers=scim_headers(token),
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "Replace", "path": "active", "value": False}
            ],
        },
    )
    assert suspended.status_code == 200
    assert suspended.json()["active"] is False
    assert member_client.get("/api/v1/auth/me").status_code == 401

    stored = services.account_repository.get_membership(
        user_id=user["id"],
        owner_id=owner_id,
        include_suspended=True,
    )
    assert stored["suspended_at"] is not None
    assert stored["scim_managed"] is True

    reactivated = client.patch(
        f"/scim/v2/Users/{membership_id}",
        headers=scim_headers(token),
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "Replace", "path": "active", "value": True}
            ],
        },
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["active"] is True
    active = services.account_repository.get_membership(
        user_id=user["id"],
        owner_id=owner_id,
    )
    assert active["suspended_at"] is None


def test_scim_group_role_precedence_and_fallback() -> None:
    client, services = build_client()
    owner = register_owner(client)
    owner_id = owner["workspace"]["id"]
    token = rotate_scim_token(client)
    user = create_scim_user(client, token)
    membership_id = user["id"]

    analyst_group = client.post(
        "/scim/v2/Groups",
        headers=scim_headers(token),
        json={
            "displayName": "Analysts",
            "externalId": "group-analysts",
            "members": [{"value": membership_id}],
        },
    )
    assert analyst_group.status_code == 201
    analyst_group_id = analyst_group.json()["id"]

    mapped = client.patch(
        f"/api/v1/team/scim-groups/{analyst_group_id}",
        headers=csrf_headers(client),
        json={"mapped_role": "analyst"},
    )
    assert mapped.status_code == 200

    provisioned = services.account_repository.find_user_by_email(
        "viewer@example.com"
    )
    membership = services.account_repository.get_membership(
        user_id=provisioned["id"],
        owner_id=owner_id,
    )
    assert membership["role"] == "analyst"

    admin_group = client.post(
        "/scim/v2/Groups",
        headers=scim_headers(token),
        json={
            "displayName": "Admins",
            "externalId": "group-admins",
            "members": [{"value": membership_id}],
        },
    )
    admin_group_id = admin_group.json()["id"]
    promoted = client.patch(
        f"/api/v1/team/scim-groups/{admin_group_id}",
        headers=csrf_headers(client),
        json={"mapped_role": "admin"},
    )
    assert promoted.status_code == 200
    membership = services.account_repository.get_membership(
        user_id=provisioned["id"],
        owner_id=owner_id,
    )
    assert membership["role"] == "admin"

    unmap_admin = client.patch(
        f"/api/v1/team/scim-groups/{admin_group_id}",
        headers=csrf_headers(client),
        json={"mapped_role": None},
    )
    assert unmap_admin.status_code == 200
    membership = services.account_repository.get_membership(
        user_id=provisioned["id"],
        owner_id=owner_id,
    )
    assert membership["role"] == "analyst"

    removed = client.patch(
        f"/scim/v2/Groups/{analyst_group_id}",
        headers=scim_headers(token),
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "Remove",
                    "path": f'members[value eq "{membership_id}"]',
                }
            ],
        },
    )
    assert removed.status_code == 200
    membership = services.account_repository.get_membership(
        user_id=provisioned["id"],
        owner_id=owner_id,
    )
    assert membership["role"] == "viewer"

    owner_mapping = client.patch(
        f"/api/v1/team/scim-groups/{admin_group_id}",
        headers=csrf_headers(client),
        json={"mapped_role": "owner"},
    )
    assert owner_mapping.status_code == 422


def test_scim_cannot_take_over_workspace_owner_and_token_rotation_revokes_old() -> None:
    client, _ = build_client()
    register_owner(client)
    first_token = rotate_scim_token(client)

    takeover = client.post(
        "/scim/v2/Users",
        headers=scim_headers(first_token),
        json={
            "userName": "owner@example.com",
            "displayName": "Owner",
            "active": True,
        },
    )
    assert takeover.status_code == 400
    assert "cannot manage a workspace owner" in takeover.json()["detail"]

    second_token = rotate_scim_token(client)
    assert second_token != first_token

    old = client.get(
        "/scim/v2/Users",
        headers=scim_headers(first_token),
    )
    assert old.status_code == 401
    fresh = client.get(
        "/scim/v2/Users",
        headers=scim_headers(second_token),
    )
    assert fresh.status_code == 200


def test_scim_config_hides_hash_and_external_id_can_be_removed() -> None:
    client, _ = build_client()
    register_owner(client)
    token = rotate_scim_token(client)

    config = client.get("/api/v1/team/scim-config")
    assert config.status_code == 200
    assert config.json()["has_token"] is True
    assert config.json()["token_prefix"]
    assert "token_hash" not in config.json()
    assert "token" not in config.json()

    user = create_scim_user(client, token)
    replaced = client.put(
        f"/scim/v2/Users/{user['id']}",
        headers=scim_headers(token),
        json={
            "userName": "viewer@example.com",
            "displayName": "Provisioned Viewer",
            "active": True,
        },
    )
    assert replaced.status_code == 200
    assert "externalId" not in replaced.json()


def test_scim_default_role_change_recomputes_unmapped_members() -> None:
    client, services = build_client()
    owner = register_owner(client)
    owner_id = owner["workspace"]["id"]

    configured = client.patch(
        "/api/v1/team/scim-config",
        headers=csrf_headers(client),
        json={"enabled": True, "default_role": "viewer"},
    )
    assert configured.status_code == 200
    token = rotate_scim_token(client)
    create_scim_user(client, token)

    provisioned = services.account_repository.find_user_by_email(
        "viewer@example.com"
    )
    membership = services.account_repository.get_membership(
        user_id=provisioned["id"],
        owner_id=owner_id,
    )
    assert membership["role"] == "viewer"

    updated = client.patch(
        "/api/v1/team/scim-config",
        headers=csrf_headers(client),
        json={"enabled": True, "default_role": "analyst"},
    )
    assert updated.status_code == 200
    membership = services.account_repository.get_membership(
        user_id=provisioned["id"],
        owner_id=owner_id,
    )
    assert membership["role"] == "analyst"
