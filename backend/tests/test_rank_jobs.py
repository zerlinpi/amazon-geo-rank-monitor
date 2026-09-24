from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    RankCheckRequest,
    SerpProduct,
    SerpResult,
)
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.workers.rank_worker import RankWorker


def engine():
    value = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(value)
    return value


def request_payload() -> dict:
    request = RankCheckRequest(
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profiles=[
            GeoProfile(
                id="ny",
                name="New York",
                marketplace="amazon.com",
                ip_country="US",
                ip_postal_code="10001",
                delivery_country="US",
                delivery_postal_code="10001",
                weight=Decimal("100"),
            )
        ],
        search_depth=100,
    )
    return request.model_dump(mode="json")


def test_claim_one_is_single_consumer_transition() -> None:
    db = engine()
    jobs = JobRepository(db)
    created = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload=request_payload(),
    )

    first = jobs.claim_one()
    second = jobs.claim_one()

    assert first["id"] == created["id"]
    assert first["status"] == "running"
    assert second is None
    assert first["attempt_count"] == 1


class FakeProvider:
    provider_name = "fake"

    async def search(self, **kwargs):
        return SerpResult(
            organic_products=[
                SerpProduct(asin="B0TARGET01", position=4, page=1),
            ]
        )


async def test_worker_runs_tenant_aware_rank_service_and_completes_job() -> None:
    db = engine()
    jobs = JobRepository(db)
    rank_repo = RankRepository(db)
    created = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload=request_payload(),
    )
    worker = RankWorker(
        job_repository=jobs,
        rank_repository=rank_repo,
        provider_registry=ProviderRegistry(
            managed=FakeProvider(),
            strict=FakeProvider(),
        ),
    )

    completed = await worker.run_once()

    assert completed["id"] == created["id"]
    assert completed["status"] == "succeeded"
    assert completed["run_id"]
    saved_run = rank_repo.get_run(completed["run_id"], owner_id="tenant-a")
    assert saved_run["owner_id"] == "tenant-a"
    assert saved_run["snapshots"][0]["weighted_rank"] == Decimal("1.00")
