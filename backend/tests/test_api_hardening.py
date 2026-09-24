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


def build_client(*, rate_limit: int = 120):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    keys = ApiKeyService(repository=tenants, pepper="test-pepper")
    services = AppServices(
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
    )
    return (
        TestClient(
            create_app(
                services,
                api_rate_limit_per_minute=rate_limit,
            )
        ),
        services,
        tenants,
        keys,
    )


def auth_for(tenants, keys, name: str):
    tenant = tenants.create_tenant(name)
    key = keys.create(owner_id=tenant["id"], name="test")
    return tenant, {"X-API-Key": key.plaintext}


def geo_payload(postal_code: str = "10001"):
    return {
        "name": f"Geo {postal_code}",
        "marketplace": "amazon.com",
        "ip_country": "US",
        "delivery_country": "US",
        "delivery_postal_code": postal_code,
        "device": "desktop",
        "weight": "100",
        "enabled": True,
    }


def test_request_id_and_structured_auth_error() -> None:
    client, _, _, _ = build_client()

    response = client.get(
        "/api/v1/geo-profiles",
        headers={"X-Request-ID": "client-request-123"},
    )

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "client-request-123"
    body = response.json()
    assert body["detail"] == "API key required"
    assert body["error"] == {
        "code": "AUTH_REQUIRED",
        "message": "API key required",
        "request_id": "client-request-123",
    }


def test_api_key_rate_limit_returns_machine_readable_429() -> None:
    client, _, tenants, keys = build_client(rate_limit=2)
    _, headers = auth_for(tenants, keys, "A")

    first = client.get("/api/v1/geo-profiles", headers=headers)
    second = client.get("/api/v1/geo-profiles", headers=headers)
    limited = client.get("/api/v1/geo-profiles", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert limited.headers["X-RateLimit-Limit"] == "2"
    assert limited.headers["X-RateLimit-Remaining"] == "0"
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.headers["X-Request-ID"]


def test_monitor_patch_and_delete_are_tenant_scoped() -> None:
    client, _, tenants, keys = build_client()
    tenant_a, auth_a = auth_for(tenants, keys, "A")
    _, auth_b = auth_for(tenants, keys, "B")

    geo_a = client.post(
        "/api/v1/geo-profiles",
        headers=auth_a,
        json=geo_payload("10001"),
    ).json()
    geo_b = client.post(
        "/api/v1/geo-profiles",
        headers=auth_a,
        json=geo_payload("90001"),
    ).json()

    created = client.post(
        "/api/v1/monitors",
        headers=auth_a,
        json={
            "name": "Walking Pad",
            "marketplace": "amazon.com",
            "keyword": "walking pad",
            "asins": ["B0TARGET01"],
            "geo_profile_ids": [geo_a["id"]],
            "search_depth": 100,
            "provider_mode": "managed",
        },
    )
    assert created.status_code == 201
    monitor_id = created.json()["id"]

    forbidden_patch = client.patch(
        f"/api/v1/monitors/{monitor_id}",
        headers=auth_b,
        json={"enabled": False},
    )
    assert forbidden_patch.status_code == 404
    assert forbidden_patch.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    updated = client.patch(
        f"/api/v1/monitors/{monitor_id}",
        headers=auth_a,
        json={
            "name": "Walking Pad US",
            "asins": ["b0target01", "B0TARGET02"],
            "geo_profile_ids": [geo_a["id"], geo_b["id"]],
            "schedule": "0 */6 * * *",
            "enabled": False,
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["owner_id"] == tenant_a["id"]
    assert body["name"] == "Walking Pad US"
    assert body["asins"] == ["B0TARGET01", "B0TARGET02"]
    assert body["geo_profile_ids"] == [geo_a["id"], geo_b["id"]]
    assert body["schedule"] == "0 */6 * * *"
    assert body["enabled"] is False

    forbidden_delete = client.delete(
        f"/api/v1/monitors/{monitor_id}",
        headers=auth_b,
    )
    assert forbidden_delete.status_code == 404

    deleted = client.delete(
        f"/api/v1/monitors/{monitor_id}",
        headers=auth_a,
    )
    assert deleted.status_code == 204
    assert client.get(
        f"/api/v1/monitors/{monitor_id}",
        headers=auth_a,
    ).status_code == 404


def test_monitor_patch_rejects_foreign_geo_profile() -> None:
    client, _, tenants, keys = build_client()
    _, auth_a = auth_for(tenants, keys, "A")
    _, auth_b = auth_for(tenants, keys, "B")

    geo_a = client.post(
        "/api/v1/geo-profiles",
        headers=auth_a,
        json=geo_payload("10001"),
    ).json()
    geo_b = client.post(
        "/api/v1/geo-profiles",
        headers=auth_b,
        json=geo_payload("90001"),
    ).json()

    monitor = client.post(
        "/api/v1/monitors",
        headers=auth_a,
        json={
            "name": "Walking Pad",
            "marketplace": "amazon.com",
            "keyword": "walking pad",
            "asins": ["B0TARGET01"],
            "geo_profile_ids": [geo_a["id"]],
            "search_depth": 100,
            "provider_mode": "managed",
        },
    ).json()

    response = client.patch(
        f"/api/v1/monitors/{monitor['id']}",
        headers=auth_a,
        json={"geo_profile_ids": [geo_b["id"]]},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
