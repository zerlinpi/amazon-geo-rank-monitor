from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.domain.errors import ProviderUnavailableError
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    RankCheckRequest,
    SerpProduct,
    SerpResult,
)
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.worker_status_repository import (
    WorkerStatusRepository,
)
from amazon_geo_rank_monitor.workers.rank_worker import RankWorker


class PartialProvider:
    provider_name = "fake"

    async def search(self, *, geo_profile, **kwargs):
        if geo_profile.id == "la":
            raise ProviderUnavailableError("timeout")
        return SerpResult(
            organic_products=[
                SerpProduct(asin="B0TARGET01", position=1, page=1),
            ]
        )


def build_request() -> RankCheckRequest:
    return RankCheckRequest(
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profiles=[
            GeoProfile(
                id="ny",
                name="New York",
                marketplace="amazon.com",
                ip_country="US",
                delivery_country="US",
                delivery_postal_code="10001",
                weight=Decimal("50"),
            ),
            GeoProfile(
                id="la",
                name="Los Angeles",
                marketplace="amazon.com",
                ip_country="US",
                delivery_country="US",
                delivery_postal_code="90001",
                weight=Decimal("50"),
            ),
        ],
        search_depth=100,
    )


async def test_worker_preserves_partial_rank_status_on_job() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    jobs = JobRepository(engine)
    ranks = RankRepository(engine)
    workers = WorkerStatusRepository(engine)
    request = build_request()
    created = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload=request.model_dump(mode="json"),
    )
    worker = RankWorker(
        job_repository=jobs,
        rank_repository=ranks,
        provider_registry=ProviderRegistry(
            managed=PartialProvider(),
            strict=PartialProvider(),
        ),
        worker_status_repository=workers,
        worker_id="worker-test",
    )

    completed = await worker.run_once()

    assert completed["id"] == created["id"]
    assert completed["status"] == "partially_succeeded"
    run = ranks.get_run(completed["run_id"], owner_id="tenant-a")
    assert run["status"] == "partially_succeeded"
    heartbeat = workers.list()[0]
    assert heartbeat["worker_id"] == "worker-test"
    assert heartbeat["status"] == "idle"
    assert heartbeat["last_job_id"] == created["id"]
    assert heartbeat["processed_jobs"] == 1
