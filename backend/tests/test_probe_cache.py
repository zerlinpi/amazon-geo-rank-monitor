from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.application.rank_application import execute_rank_check
from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    RankCheckRequest,
    SerpProduct,
    SerpResult,
    VerificationLevel,
)
from amazon_geo_rank_monitor.monitor.service import RankMonitorService
from amazon_geo_rank_monitor.probe_cache import ProbeCacheService
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.models import Base, TenantRow
from amazon_geo_rank_monitor.repositories.probe_cache_repository import (
    ProbeCacheRepository,
)
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository


class CountingProvider:
    provider_name = "fake"
    verification_level = VerificationLevel.MANAGED

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def search(self, **kwargs):
        geo = kwargs["geo_profile"]
        self.calls.append((geo.id, geo.delivery_postal_code))
        return SerpResult(
            organic_products=[
                SerpProduct(asin="B0TARGET01", position=4, page=1),
            ]
        )


class StrictCountingProvider(CountingProvider):
    verification_level = VerificationLevel.STRICT


def engine():
    value = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(value)
    with value.begin() as connection:
        connection.execute(
            TenantRow.__table__.insert(),
            [
                {"id": "tenant-a", "name": "Tenant A"},
                {"id": "tenant-b", "name": "Tenant B"},
            ],
        )
    return value


def geo(
    profile_id: str = "ny",
    *,
    zip_code: str = "10001",
    weight: str = "100",
) -> GeoProfile:
    return GeoProfile(
        id=profile_id,
        name=profile_id,
        marketplace="amazon.com",
        ip_country="US",
        ip_state="NY",
        ip_city="New York",
        ip_postal_code=zip_code,
        delivery_country="US",
        delivery_postal_code=zip_code,
        device="desktop",
        weight=Decimal(weight),
    )


def request(profile: GeoProfile) -> RankCheckRequest:
    return RankCheckRequest(
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profiles=[profile],
        search_depth=100,
    )


def cache_service(db, *, managed_ttl: int = 300, strict_ttl: int = 0):
    return ProbeCacheService(
        repository=ProbeCacheRepository(db),
        managed_ttl_seconds=managed_ttl,
        strict_ttl_seconds=strict_ttl,
        retention_hours=24,
    )


@pytest.mark.asyncio
async def test_second_identical_probe_uses_cache_and_preserves_provenance() -> None:
    db = engine()
    provider = CountingProvider()
    ranks = RankRepository(db)
    cache = cache_service(db)
    service = RankMonitorService(
        provider=provider,
        repository=ranks,
        probe_cache=cache,
        provider_mode="managed",
    )
    payload = request(geo())

    first = await service.check_with_result(payload, owner_id="tenant-a")
    second = await service.check_with_result(payload, owner_id="tenant-a")

    assert provider.calls == [("ny", "10001")]
    assert first.upstream_probe_count == 1
    assert first.cache_hit_count == 0
    assert second.upstream_probe_count == 0
    assert second.cache_hit_count == 1
    assert second.observations[0].probe_source == "cache"
    assert second.observations[0].cache_age_seconds is not None

    saved = ranks.get_run(second.run_id, owner_id="tenant-a")
    assert saved["settled_probe_count"] == 0
    assert saved["cache_hit_count"] == 1
    assert saved["observations"][0]["probe_source"] == "cache"


@pytest.mark.asyncio
async def test_geo_address_change_misses_cache() -> None:
    db = engine()
    provider = CountingProvider()
    service = RankMonitorService(
        provider=provider,
        repository=RankRepository(db),
        probe_cache=cache_service(db),
        provider_mode="managed",
    )

    await service.check_with_result(request(geo(zip_code="10001")), owner_id="tenant-a")
    await service.check_with_result(request(geo(zip_code="10002")), owner_id="tenant-a")

    assert provider.calls == [("ny", "10001"), ("ny", "10002")]


@pytest.mark.asyncio
async def test_weight_only_change_reuses_compatible_serp() -> None:
    db = engine()
    provider = CountingProvider()
    service = RankMonitorService(
        provider=provider,
        repository=RankRepository(db),
        probe_cache=cache_service(db),
        provider_mode="managed",
    )

    await service.check_with_result(request(geo(weight="30")), owner_id="tenant-a")
    second = await service.check_with_result(
        request(geo(weight="70")),
        owner_id="tenant-a",
    )

    assert len(provider.calls) == 1
    assert second.cache_hit_count == 1


@pytest.mark.asyncio
async def test_cache_is_never_shared_between_tenants() -> None:
    db = engine()
    provider = CountingProvider()
    service = RankMonitorService(
        provider=provider,
        repository=RankRepository(db),
        probe_cache=cache_service(db),
        provider_mode="managed",
    )
    payload = request(geo())

    await service.check_with_result(payload, owner_id="tenant-a")
    second = await service.check_with_result(payload, owner_id="tenant-b")

    assert len(provider.calls) == 2
    assert second.cache_hit_count == 0
    assert second.upstream_probe_count == 1


@pytest.mark.asyncio
async def test_strict_provider_cache_is_disabled_by_default() -> None:
    db = engine()
    provider = StrictCountingProvider()
    service = RankMonitorService(
        provider=provider,
        repository=RankRepository(db),
        probe_cache=cache_service(db),
        provider_mode="strict",
    )
    payload = request(geo())

    first = await service.check_with_result(payload, owner_id="tenant-a")
    second = await service.check_with_result(payload, owner_id="tenant-a")

    assert len(provider.calls) == 2
    assert first.cache_hit_count == 0
    assert second.cache_hit_count == 0


@pytest.mark.asyncio
async def test_full_cache_hit_runs_with_zero_available_credits() -> None:
    db = engine()
    provider = CountingProvider()
    geo_repository = GeoRepository(db)
    billing = BillingRepository(db)
    cache = cache_service(db)
    services = AppServices(
        tenant_repository=None,
        geo_repository=geo_repository,
        monitor_repository=None,
        job_repository=None,
        rank_repository=RankRepository(db),
        api_keys=None,
        provider_registry=ProviderRegistry(
            managed=provider,
            strict=provider,
        ),
        probe_cache_repository=ProbeCacheRepository(db),
        probe_cache=cache,
        billing_repository=billing,
        rate_card=RateCard(managed_serp=1, browser_verified_serp=5),
    )
    created_geo = geo_repository.create(
        owner_id="tenant-a",
        profile=geo(),
    )
    billing.grant(
        owner_id="tenant-a",
        credits=1,
        idempotency_key="grant:cache-test",
    )

    first = await execute_rank_check(
        services=services,
        owner_id="tenant-a",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[created_geo["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="cache-first",
    )
    assert first.upstream_probe_count == 1
    assert billing.get_balance("tenant-a")["available"] == 0

    second = await execute_rank_check(
        services=services,
        owner_id="tenant-a",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[created_geo["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="cache-second",
    )

    assert len(provider.calls) == 1
    assert second.upstream_probe_count == 0
    assert second.cache_hit_count == 1
    assert billing.get_balance("tenant-a") == {
        "balance": 0,
        "reserved": 0,
        "available": 0,
    }
