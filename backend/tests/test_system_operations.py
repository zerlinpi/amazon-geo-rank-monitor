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
from amazon_geo_rank_monitor.repositories.worker_status_repository import (
    WorkerStatusRepository,
)


class FakeProvider:
    provider_name = "fake"

    async def search(self, **kwargs):
        return SerpResult()


def build_system_client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    tenants = TenantRepository(engine)
    keys = ApiKeyService(repository=tenants, pepper="pepper")
    jobs = JobRepository(engine, default_max_attempts=1)
    workers = WorkerStatusRepository(engine)
    services = AppServices(
        tenant_repository=tenants,
        geo_repository=GeoRepository(engine),
        monitor_repository=MonitorRepository(engine),
        job_repository=jobs,
        rank_repository=RankRepository(engine),
        api_keys=keys,
        provider_registry=ProviderRegistry(
            managed=FakeProvider(),
            strict=FakeProvider(),
        ),
        database_engine=engine,
        worker_status_repository=workers,
    )
    return TestClient(create_app(services)), tenants, keys, jobs, workers


def test_system_queue_metrics_and_dead_letter_requeue_are_scoped() -> None:
    client, tenants, keys, jobs, workers = build_system_client()
    tenant = tenants.create_tenant("Acme")
    root = keys.create(owner_id=tenant["id"], name="root")
    reader = keys.create(
        owner_id=tenant["id"],
        name="ops reader",
        scopes=["system:read"],
    )
    root_headers = {"X-API-Key": root.plaintext}
    read_headers = {"X-API-Key": reader.plaintext}

    created = jobs.enqueue(
        owner_id=tenant["id"],
        provider_mode="managed",
        request_payload={"keyword": "walking pad"},
    )
    jobs.claim_one(worker_id="worker-a", lease_seconds=60)
    jobs.retry_or_dead_letter(created["id"], error="fatal")
    workers.heartbeat(
        worker_id="worker-a",
        status="dead_letter",
        last_job_id=created["id"],
        last_error="fatal",
        processed_delta=1,
    )

    queue = client.get("/api/v1/system/queue", headers=read_headers)
    assert queue.status_code == 200
    assert queue.json()["counts"]["dead_letter"] == 1

    dead_letters = client.get(
        "/api/v1/system/dead-letters",
        headers=read_headers,
    )
    assert dead_letters.status_code == 200
    assert dead_letters.json()[0]["id"] == created["id"]

    metrics = client.get("/api/v1/system/metrics", headers=read_headers)
    assert metrics.status_code == 200
    assert 'agrm_rank_jobs{status="dead_letter"} 1' in metrics.text
    assert "agrm_service_heartbeat_age_seconds" in metrics.text
    assert "agrm_service_processed_jobs_total" in metrics.text

    denied = client.post(
        f"/api/v1/system/dead-letters/{created['id']}/requeue",
        headers=read_headers,
    )
    assert denied.status_code == 403

    requeued = client.post(
        f"/api/v1/system/dead-letters/{created['id']}/requeue",
        headers=root_headers,
    )
    assert requeued.status_code == 200
    assert requeued.json()["status"] == "pending"
    assert requeued.json()["attempt_count"] == 0
