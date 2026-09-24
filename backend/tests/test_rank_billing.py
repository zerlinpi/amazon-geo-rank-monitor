from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.billing.usage import RankUsageMeter
from amazon_geo_rank_monitor.domain.errors import ProviderUnavailableError
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    RankCheckRequest,
    SerpProduct,
    SerpResult,
)
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.workers.rank_worker import RankWorker


class RecordingProvider:
    provider_name = "fake"

    def __init__(self, fail_geo: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_geo = fail_geo

    async def search(self, **kwargs):
        geo = kwargs["geo_profile"]
        self.calls.append(geo.id)
        if geo.id == self.fail_geo:
            raise ProviderUnavailableError("timeout")
        return SerpResult(
            organic_products=[
                SerpProduct(asin=f"B0ASIN{i:04d}", position=i + 1, page=1)
                for i in range(10)
            ]
        )


def setup():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return (
        JobRepository(engine),
        RankRepository(engine),
        BillingRepository(engine),
    )


def request_payload(asin_count: int = 10) -> dict:
    profiles = [
        GeoProfile(
            id=geo_id,
            name=geo_id,
            marketplace="amazon.com",
            ip_country="US",
            delivery_country="US",
            delivery_postal_code=postal,
            weight=Decimal(weight),
        )
        for geo_id, postal, weight in [
            ("ny", "10001", "30"),
            ("la", "90001", "40"),
            ("tx", "75201", "30"),
        ]
    ]
    request = RankCheckRequest(
        marketplace="amazon.com",
        keyword="walking pad",
        asins=[f"B0ASIN{i:04d}" for i in range(asin_count)],
        geo_profiles=profiles,
        search_depth=100,
    )
    return request.model_dump(mode="json")


async def test_ten_asins_across_three_geos_charge_three_managed_probes() -> None:
    jobs, ranks, billing = setup()
    billing.grant(
        owner_id="tenant-a",
        amount=10,
        idempotency_key="grant",
        reference_type="test",
        reference_id="seed",
    )
    job = jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload=request_payload(10),
    )
    provider = RecordingProvider()
    meter = RankUsageMeter(
        billing_repository=billing,
        rate_card=RateCard(managed_serp_credits=1, strict_serp_credits=5),
    )
    worker = RankWorker(
        job_repository=jobs,
        rank_repository=ranks,
        provider_registry=ProviderRegistry(managed=provider, strict=provider),
        usage_meter=meter,
    )

    completed = await worker.run_once()

    assert completed["id"] == job["id"]
    assert completed["status"] == "succeeded"
    assert provider.calls == ["ny", "la", "tx"]
    account = billing.get_account("tenant-a")
    assert account["available_credits"] == 7
    assert account["reserved_credits"] == 0


async def test_insufficient_credits_fail_before_provider_call() -> None:
    jobs, ranks, billing = setup()
    billing.grant(
        owner_id="tenant-a",
        amount=2,
        idempotency_key="grant",
        reference_type="test",
        reference_id="seed",
    )
    jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload=request_payload(10),
    )
    provider = RecordingProvider()
    worker = RankWorker(
        job_repository=jobs,
        rank_repository=ranks,
        provider_registry=ProviderRegistry(managed=provider, strict=provider),
        usage_meter=RankUsageMeter(
            billing_repository=billing,
            rate_card=RateCard(),
        ),
    )

    completed = await worker.run_once()

    assert completed["status"] == "failed"
    assert completed["error"].startswith("INSUFFICIENT_CREDITS:")
    assert provider.calls == []
    assert billing.get_account("tenant-a")["available_credits"] == 2


async def test_partial_probe_success_consumes_only_successful_probes() -> None:
    jobs, ranks, billing = setup()
    billing.grant(
        owner_id="tenant-a",
        amount=10,
        idempotency_key="grant",
        reference_type="test",
        reference_id="seed",
    )
    jobs.enqueue(
        owner_id="tenant-a",
        provider_mode="managed",
        request_payload=request_payload(2),
    )
    provider = RecordingProvider(fail_geo="la")
    worker = RankWorker(
        job_repository=jobs,
        rank_repository=ranks,
        provider_registry=ProviderRegistry(managed=provider, strict=provider),
        usage_meter=RankUsageMeter(
            billing_repository=billing,
            rate_card=RateCard(),
        ),
    )

    completed = await worker.run_once()

    assert completed["status"] == "succeeded"
    run = ranks.get_run(completed["run_id"], owner_id="tenant-a")
    assert run["status"] == "partially_succeeded"
    assert run["settled_probe_count"] == 2
    account = billing.get_account("tenant-a")
    assert account["available_credits"] == 8
    assert account["reserved_credits"] == 0
