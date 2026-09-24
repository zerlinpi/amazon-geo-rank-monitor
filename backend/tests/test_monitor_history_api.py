from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.domain.models import GeoProfile, SerpProduct, SerpResult
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository
from amazon_geo_rank_monitor.workers.rank_worker import RankWorker


class FakeProvider:
    provider_name = "fake"

    async def search(self, **kwargs):
        return SerpResult(
            organic_products=[
                SerpProduct(asin="B0TARGET01", position=1, page=1),
            ]
        )


async def test_monitor_history_returns_job_and_completed_run() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    geo_repository = GeoRepository(engine)
    monitor_repository = MonitorRepository(engine)
    job_repository = JobRepository(engine)
    rank_repository = RankRepository(engine)
    api_keys = ApiKeyService(repository=tenants, pepper="test-pepper")
    providers = ProviderRegistry(managed=FakeProvider(), strict=FakeProvider())
    services = AppServices(
        tenant_repository=tenants,
        geo_repository=geo_repository,
        monitor_repository=monitor_repository,
        job_repository=job_repository,
        rank_repository=rank_repository,
        api_keys=api_keys,
        provider_registry=providers,
    )
    client = TestClient(create_app(services))
    tenant = tenants.create_tenant("A")
    key = api_keys.create(owner_id=tenant["id"], name="test")
    headers = {"X-API-Key": key.plaintext}
    geo = geo_repository.create(
        owner_id=tenant["id"],
        profile=GeoProfile(
            id="ny",
            name="New York",
            marketplace="amazon.com",
            ip_country="US",
            delivery_country="US",
            delivery_postal_code="10001",
            weight=Decimal("100"),
        ),
    )
    monitor = monitor_repository.create(
        owner_id=tenant["id"],
        name="Walking Pad",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[geo["id"]],
        search_depth=100,
        provider_mode="managed",
    )
    queued = client.post(
        f"/api/v1/monitors/{monitor['id']}/run",
        headers=headers,
    )
    assert queued.status_code == 202

    worker = RankWorker(
        job_repository=job_repository,
        rank_repository=rank_repository,
        provider_registry=providers,
    )
    await worker.run_once()

    response = client.get(
        f"/api/v1/monitors/{monitor['id']}/history",
        headers=headers,
    )
    assert response.status_code == 200
    history = response.json()
    assert len(history) == 1
    assert history[0]["job"]["status"] == "succeeded"
    assert history[0]["run"]["status"] == "succeeded"
    assert history[0]["run"]["snapshots"][0]["asin"] == "B0TARGET01"
