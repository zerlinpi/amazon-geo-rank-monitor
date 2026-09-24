from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.application.rank_application import execute_rank_check
from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.domain.errors import InsufficientCreditsError
from amazon_geo_rank_monitor.domain.models import GeoProfile, SerpProduct, SerpResult
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.models import Base, TenantRow
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository


class CountingProvider:
    provider_name = "fake"

    def __init__(self, fail_zip: str | None = None) -> None:
        self.calls = 0
        self.fail_zip = fail_zip

    async def search(self, **kwargs):
        from amazon_geo_rank_monitor.domain.errors import ProviderUnavailableError

        self.calls += 1
        geo = kwargs["geo_profile"]
        if geo.delivery_postal_code == self.fail_zip:
            raise ProviderUnavailableError("timeout")
        return SerpResult(
            organic_products=[SerpProduct(asin="B0TARGET01", position=4)]
        )


def make_services(provider):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            TenantRow.__table__.insert().values(id="tenant-1", name="Tenant")
        )
    geo = GeoRepository(engine)
    billing = BillingRepository(engine)
    services = AppServices(
        tenant_repository=None,
        geo_repository=geo,
        monitor_repository=None,
        job_repository=None,
        rank_repository=RankRepository(engine),
        api_keys=None,
        provider_registry=ProviderRegistry(managed=provider, strict=provider),
        billing_repository=billing,
        rate_card=RateCard(managed_serp=1, browser_verified_serp=5),
    )
    return services, geo, billing


def add_geo(repo, profile_id, zip_code):
    return repo.create(
        owner_id="tenant-1",
        profile=GeoProfile(
            id=profile_id,
            name=profile_id,
            marketplace="amazon.com",
            ip_country="US",
            delivery_country="US",
            delivery_postal_code=zip_code,
            weight=Decimal("1"),
        ),
    )


@pytest.mark.asyncio
async def test_insufficient_credits_fail_before_provider_call() -> None:
    provider = CountingProvider()
    services, geo, _ = make_services(provider)
    item = add_geo(geo, "ny", "10001")
    with pytest.raises(InsufficientCreditsError):
        await execute_rank_check(
            services=services,
            owner_id="tenant-1",
            marketplace="amazon.com",
            keyword="walking pad",
            asins=["B0TARGET01"],
            geo_profile_ids=[item["id"]],
            search_depth=100,
            provider_mode="managed",
            reference_id="req-1",
        )
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_partial_success_settles_only_successful_probe_cost() -> None:
    provider = CountingProvider(fail_zip="90001")
    services, geo, billing = make_services(provider)
    ny = add_geo(geo, "ny", "10001")
    la = add_geo(geo, "la", "90001")
    billing.grant(owner_id="tenant-1", credits=10, idempotency_key="grant:1")

    result = await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[ny["id"], la["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="req-2",
    )

    assert result.status == "partially_succeeded"
    assert provider.calls == 2
    assert billing.get_balance("tenant-1") == {
        "balance": 9,
        "reserved": 0,
        "available": 9,
    }
