from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.domain.models import SerpResult
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
    keys = ApiKeyService(repository=tenants, pepper="pepper")
    app = create_app(
        AppServices(
            tenant_repository=tenants,
            geo_repository=GeoRepository(engine),
            monitor_repository=MonitorRepository(engine),
            job_repository=JobRepository(engine),
            rank_repository=RankRepository(engine),
            api_keys=keys,
            provider_registry=ProviderRegistry(
                managed=FakeProvider(),
                strict=FakeProvider(),
            ),
            database_engine=engine,
        )
    )
    return TestClient(app), tenants, keys


def geo_payload():
    return {
        "id": "client-value",
        "name": "New York",
        "marketplace": "amazon.com",
        "ip_country": "US",
        "delivery_country": "US",
        "delivery_postal_code": "10001",
        "device": "desktop",
        "weight": "100",
        "enabled": True,
    }


def test_read_only_key_can_read_but_not_write_geo_profiles() -> None:
    client, tenants, keys = build_client()
    tenant = tenants.create_tenant("Acme")
    root = keys.create(owner_id=tenant["id"], name="root")
    root_headers = {"X-API-Key": root.plaintext}

    assert client.post(
        "/api/v1/geo-profiles",
        headers=root_headers,
        json=geo_payload(),
    ).status_code == 201

    reader = keys.create(
        owner_id=tenant["id"],
        name="reader",
        scopes=["geo:read"],
    )
    headers = {"X-API-Key": reader.plaintext}

    assert client.get("/api/v1/geo-profiles", headers=headers).status_code == 200
    denied = client.post(
        "/api/v1/geo-profiles",
        headers=headers,
        json=geo_payload(),
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"
    assert "geo:write" in denied.json()["detail"]


def test_key_management_requires_keys_manage_scope() -> None:
    client, tenants, keys = build_client()
    tenant = tenants.create_tenant("Acme")
    reader = keys.create(
        owner_id=tenant["id"],
        name="reader",
        scopes=["rank:read"],
    )

    denied = client.get(
        "/api/v1/api-keys",
        headers={"X-API-Key": reader.plaintext},
    )

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"


def test_api_key_creation_persists_requested_scopes() -> None:
    client, tenants, keys = build_client()
    tenant = tenants.create_tenant("Acme")
    root = keys.create(owner_id=tenant["id"], name="root")

    created = client.post(
        "/api/v1/api-keys",
        headers={"X-API-Key": root.plaintext},
        json={
            "name": "rank reader",
            "scopes": ["rank:read", "monitors:read"],
        },
    )

    assert created.status_code == 201
    assert created.json()["scopes"] == ["rank:read", "monitors:read"]
    rows = client.get(
        "/api/v1/api-keys",
        headers={"X-API-Key": root.plaintext},
    ).json()
    row = next(item for item in rows if item["id"] == created.json()["id"])
    assert row["scopes"] == ["rank:read", "monitors:read"]


def test_unknown_api_key_scope_is_rejected() -> None:
    client, tenants, keys = build_client()
    tenant = tenants.create_tenant("Acme")
    root = keys.create(owner_id=tenant["id"], name="root")

    response = client.post(
        "/api/v1/api-keys",
        headers={"X-API-Key": root.plaintext},
        json={"name": "bad", "scopes": ["admin:everything"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_ready_checks_database_connectivity() -> None:
    client, _, _ = build_client()

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
