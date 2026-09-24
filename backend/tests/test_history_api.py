from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from amazon_geo_rank_monitor.api.app import AppServices, create_app
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository


class NullProvider:
    provider_name = "null"

    async def search(self, **kwargs):
        raise AssertionError("provider should not be called")


def setup():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    jobs = JobRepository(engine)
    ranks = RankRepository(engine)
    keys = ApiKeyService(repository=tenants, pepper="pepper")
    provider = NullProvider()
    services = AppServices(
        tenant_repository=tenants,
        geo_repository=GeoRepository(engine),
        monitor_repository=MonitorRepository(engine),
        job_repository=jobs,
        rank_repository=ranks,
        api_keys=keys,
        provider_registry=ProviderRegistry(managed=provider, strict=provider),
    )
    return TestClient(create_app(services)), services


def auth(services, name: str):
    tenant = services.tenant_repository.create_tenant(name)
    key = services.api_keys.create(owner_id=tenant["id"], name="test")
    return tenant, {"X-API-Key": key.plaintext}


def make_monitor(services, owner_id: str, name: str) -> dict:
    profile = services.geo_repository.create(
        owner_id=owner_id,
        profile=__import__(
            "amazon_geo_rank_monitor.domain.models",
            fromlist=["GeoProfile"],
        ).GeoProfile(
            id="source-id",
            name=f"{name} Geo",
            marketplace="amazon.com",
            ip_country="US",
            delivery_country="US",
            delivery_postal_code="10001",
            weight=1,
        ),
    )
    return services.monitor_repository.create(
        owner_id=owner_id,
        name=name,
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[profile["id"]],
        search_depth=100,
        provider_mode="managed",
    )


def test_runs_and_jobs_list_are_tenant_scoped() -> None:
    client, services = setup()
    a, auth_a = auth(services, "A")
    b, auth_b = auth(services, "B")

    run_a = services.rank_repository.create_run(
        marketplace="amazon.com",
        keyword="walking pad",
        requested_probe_count=1,
        owner_id=a["id"],
    )
    services.rank_repository.complete_run(
        run_a,
        status="succeeded",
        settled_probe_count=1,
    )
    run_b = services.rank_repository.create_run(
        marketplace="amazon.com",
        keyword="desk treadmill",
        requested_probe_count=1,
        owner_id=b["id"],
    )
    services.rank_repository.complete_run(
        run_b,
        status="succeeded",
        settled_probe_count=1,
    )
    services.job_repository.enqueue(
        owner_id=a["id"],
        provider_mode="managed",
        request_payload={"a": 1},
    )
    services.job_repository.enqueue(
        owner_id=b["id"],
        provider_mode="managed",
        request_payload={"b": 1},
    )

    runs_a = client.get("/api/v1/runs", headers=auth_a)
    jobs_a = client.get("/api/v1/jobs", headers=auth_a)
    runs_b = client.get("/api/v1/runs", headers=auth_b)

    assert {item["id"] for item in runs_a.json()} == {run_a}
    assert len(jobs_a.json()) == 1
    assert jobs_a.json()[0]["owner_id"] == a["id"]
    assert {item["id"] for item in runs_b.json()} == {run_b}


def test_monitor_history_links_jobs_to_runs_and_hides_other_tenants() -> None:
    client, services = setup()
    a, auth_a = auth(services, "A")
    _, auth_b = auth(services, "B")
    monitor = make_monitor(services, a["id"], "Walking Pad")

    run_id = services.rank_repository.create_run(
        marketplace="amazon.com",
        keyword="walking pad",
        requested_probe_count=1,
        owner_id=a["id"],
    )
    services.rank_repository.complete_run(
        run_id,
        status="succeeded",
        settled_probe_count=1,
    )
    job = services.job_repository.enqueue(
        owner_id=a["id"],
        monitor_target_id=monitor["id"],
        provider_mode="managed",
        request_payload={"example": True},
    )
    claimed = services.job_repository.claim_one()
    assert claimed["id"] == job["id"]
    services.job_repository.complete(job["id"], run_id=run_id)

    history = client.get(
        f"/api/v1/monitors/{monitor['id']}/history",
        headers=auth_a,
    )
    forbidden = client.get(
        f"/api/v1/monitors/{monitor['id']}/history",
        headers=auth_b,
    )

    assert history.status_code == 200
    assert history.json()[0]["job"]["id"] == job["id"]
    assert history.json()[0]["run"]["id"] == run_id
    assert forbidden.status_code == 404
