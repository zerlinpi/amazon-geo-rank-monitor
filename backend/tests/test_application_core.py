from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    RankCheckRequest,
    SerpProduct,
    SerpResult,
    VerificationLevel,
)
from amazon_geo_rank_monitor.monitor.service import RankMonitorService
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository


class FakeProvider:
    provider_name = "fake"

    def __init__(self, level: VerificationLevel) -> None:
        self.verification_level = level

    async def search(self, **kwargs):
        return SerpResult(
            organic_products=[SerpProduct(asin="B0TARGET01", position=4)]
        )


def make_request() -> RankCheckRequest:
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
                weight=Decimal("1"),
            )
        ],
        search_depth=100,
    )


@pytest.mark.asyncio
async def test_check_with_result_returns_run_identity_and_owner() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = RankRepository(engine)
    service = RankMonitorService(
        provider=FakeProvider(VerificationLevel.STRICT),
        repository=repository,
    )

    result = await service.check_with_result(make_request(), owner_id="tenant-1")

    assert result.run_id
    assert result.status == "succeeded"
    assert result.snapshots[0].weighted_rank == Decimal("1.00")
    assert result.observations[0].verification_level == VerificationLevel.STRICT
    saved = repository.get_run(result.run_id, owner_id="tenant-1")
    assert saved["owner_id"] == "tenant-1"
    with pytest.raises(KeyError):
        repository.get_run(result.run_id, owner_id="tenant-2")


def test_provider_registry_routes_managed_and_strict() -> None:
    managed = FakeProvider(VerificationLevel.MANAGED)
    strict = FakeProvider(VerificationLevel.STRICT)
    registry = ProviderRegistry(managed=managed, strict=strict)
    assert registry.get("managed") is managed
    assert registry.get("strict") is strict
    with pytest.raises(ValueError):
        registry.get("unknown")
