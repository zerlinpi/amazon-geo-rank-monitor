from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.domain.models import SerpProduct, SerpResult
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository


class FakeProvider:
    provider_name = "fake"

    async def search(self, **kwargs):
        return SerpResult(
            organic_products=[
                SerpProduct(asin="B0TARGET01", position=4, page=1),
            ]
        )


def setup_client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    geo = GeoRepository(engine)
    monitors = MonitorRepository(engine)
    jobs = JobRepository(engine)
    ranks = RankRepository(engine)
    keys = ApiKeyService(repository=tenants, pepper="test-pepper")
    providers = ProviderRegistry(managed=FakeProvider(), strict=FakeProvider())
    app = create_app(
        AppServices(
            tenant_repository=tenants,
            geo_repository=geo,
            monitor_repository=monitors,
            job_repository=jobs,
            rank_repository=ranks,
            api_keys=keys,
            provider_registry=providers,
        )
    )
    return TestClient(app), tenants, keys


def create_auth(tenants, keys, name):
    tenant = tenants.create_tenant(name)
    key = keys.create(owner_id=tenant["id"], name="test")
    return tenant, {"X-API-Key": key.plaintext}


def geo_payload():
    return {
        "id": "client-value-is-ignored",
        "name": "New York",
        "marketplace": "amazon.com",
        "ip_country": "US",
        "ip_state": "NY",
        "ip_city": "New York",
        "ip_postal_code": "10001",
        "delivery_country": "US",
        "delivery_postal_code": "10001",
        "device": "desktop",
        "weight": "100",
        "enabled": True,
    }


def test_health_is_public_but_resources_require_api_key() -> None:
    client, _, _ = setup_client()
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/geo-profiles").status_code == 401


def test_geo_and_monitor_resources_are_tenant_scoped() -> None:
    client, tenants, keys = setup_client()
    tenant_a, auth_a = create_auth(tenants, keys, "A")
    _, auth_b = create_auth(tenants, keys, "B")

    geo = client.post("/api/v1/geo-profiles", headers=auth_a, json=geo_payload())
    assert geo.status_code == 201
    geo_id = geo.json()["id"]

    monitor = client.post(
        "/api/v1/monitors",
        headers=auth_a,
        json={
            "name": "Walking Pad",
            "marketplace": "amazon.com",
            "keyword": "walking pad",
            "asins": ["B0TARGET01"],
            "geo_profile_ids": [geo_id],
            "search_depth": 100,
            "provider_mode": "managed",
        },
    )
    assert monitor.status_code == 201
    monitor_id = monitor.json()["id"]
    assert client.get(f"/api/v1/monitors/{monitor_id}", headers=auth_a).status_code == 200
    assert client.get(f"/api/v1/monitors/{monitor_id}", headers=auth_b).status_code == 404

    queued = client.post(f"/api/v1/monitors/{monitor_id}/run", headers=auth_a)
    assert queued.status_code == 202
    job = client.get(f"/api/v1/jobs/{queued.json()['id']}", headers=auth_a)
    assert job.status_code == 200
    assert job.json()["status"] == "pending"
    assert job.json()["owner_id"] == tenant_a["id"]


def test_immediate_rank_check_creates_tenant_owned_run() -> None:
    client, tenants, keys = setup_client()
    tenant, auth = create_auth(tenants, keys, "A")
    geo = client.post("/api/v1/geo-profiles", headers=auth, json=geo_payload()).json()

    response = client.post(
        "/api/v1/rank/check",
        headers=auth,
        json={
            "marketplace": "amazon.com",
            "keyword": "walking pad",
            "asins": ["B0TARGET01"],
            "geo_profile_ids": [geo["id"]],
            "search_depth": 100,
            "provider_mode": "managed",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["snapshots"][0]["weighted_rank"] == "1.00"

    run = client.get(f"/api/v1/runs/{body['run_id']}", headers=auth)
    assert run.status_code == 200
    assert run.json()["owner_id"] == tenant["id"]


def test_api_key_creation_returns_plaintext_once_and_listing_hides_hash() -> None:
    client, tenants, keys = setup_client()
    _, auth = create_auth(tenants, keys, "A")
    created = client.post(
        "/api/v1/api-keys",
        headers=auth,
        json={"name": "automation"},
    )
    assert created.status_code == 201
    assert created.json()["plaintext"].startswith("agrm_")

    listed = client.get("/api/v1/api-keys", headers=auth)
    assert listed.status_code == 200
    assert all("key_hash" not in item for item in listed.json())
    assert all("plaintext" not in item for item in listed.json())


def test_run_list_is_tenant_scoped() -> None:
    client, tenants, keys = setup_client()
    _, auth_a = create_auth(tenants, keys, "A")
    _, auth_b = create_auth(tenants, keys, "B")
    geo = client.post("/api/v1/geo-profiles", headers=auth_a, json=geo_payload()).json()

    response = client.post(
        "/api/v1/rank/check",
        headers=auth_a,
        json={
            "marketplace": "amazon.com",
            "keyword": "walking pad",
            "asins": ["B0TARGET01"],
            "geo_profile_ids": [geo["id"]],
            "search_depth": 100,
            "provider_mode": "managed",
        },
    )
    assert response.status_code == 200

    runs_a = client.get("/api/v1/runs", headers=auth_a)
    runs_b = client.get("/api/v1/runs", headers=auth_b)
    assert runs_a.status_code == 200
    assert len(runs_a.json()) == 1
    assert runs_a.json()[0]["keyword"] == "walking pad"
    assert runs_b.json() == []


def test_configured_cors_origin_is_allowed() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    keys = ApiKeyService(repository=tenants, pepper="test-pepper")
    app = create_app(
        AppServices(
            tenant_repository=tenants,
            geo_repository=GeoRepository(engine),
            monitor_repository=MonitorRepository(engine),
            job_repository=JobRepository(engine),
            rank_repository=RankRepository(engine),
            api_keys=keys,
            provider_registry=ProviderRegistry(managed=FakeProvider(), strict=FakeProvider()),
        ),
        cors_origins=["http://localhost:5173"],
    )
    client = TestClient(app)
    response = client.options(
        "/api/v1/geo-profiles",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
