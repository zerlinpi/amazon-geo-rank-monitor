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
from amazon_geo_rank_monitor.verification import (
    AutoStrictVerificationPolicy,
    AutoStrictVerifier,
)
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

    def __init__(self, position: int = 4) -> None:
        self.position = position
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        return SerpResult(
            organic_products=[
                SerpProduct(
                    asin="B0TARGET01",
                    position=self.position,
                    page=1,
                ),
            ]
        )


async def test_worker_runs_tenant_aware_rank_service_and_completes_job() -> None:
    db = engine()
    jobs = JobRepository(db)
    rank_repo = RankRepository(db)
    payload = request_payload()
    payload["_verification_policy"] = {
        "enabled": None,
        "min_confidence": None,
        "max_upstream_probes_per_run": None,
        "force_strict_verification": False,
    }
    created = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload=payload,
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


async def test_worker_honors_manual_force_when_automatic_policy_is_off() -> None:
    db = engine()
    jobs = JobRepository(db)
    rank_repo = RankRepository(db)
    managed = FakeProvider(position=4)
    strict = FakeProvider(position=7)
    payload = request_payload()
    payload["_verification_policy"] = {
        "enabled": False,
        "min_confidence": "0.75",
        "max_upstream_probes_per_run": 1,
        "force_strict_verification": True,
    }
    created = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload=payload,
    )
    verifier = AutoStrictVerifier(
        policy=AutoStrictVerificationPolicy(enabled=True),
        strict_provider=strict,
        max_upstream_probes_per_run=3,
    )
    worker = RankWorker(
        job_repository=jobs,
        rank_repository=rank_repo,
        provider_registry=ProviderRegistry(
            managed=managed,
            strict=strict,
        ),
        auto_strict_verifier=verifier,
    )

    completed = await worker.run_once()

    assert completed["id"] == created["id"]
    assert completed["status"] == "succeeded"
    assert managed.calls == 1
    assert strict.calls == 1
    saved = rank_repo.get_run(completed["run_id"], owner_id="tenant-a")
    assert saved["snapshots"][0]["weighted_rank"] == Decimal("7.00")
    assert saved["verification_metadata"]["manual_force_requested"] is True
    assert saved["verification_metadata"]["manual_force_effective"] is True
    assert saved["verification_metadata"]["auto_strict_enabled"] is False
    assert saved["verification_metadata"]["events"][0]["triggers"] == [
        "manual_force"
    ]
