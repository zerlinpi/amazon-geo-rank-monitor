from decimal import Decimal

import pytest

from amazon_geo_rank_monitor.domain.errors import ProviderUnavailableError
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    RankCheckRequest,
    SerpProduct,
    SerpResult,
    VerificationLevel,
)
from amazon_geo_rank_monitor.monitor.service import RankMonitorService


class RecordingProvider:
    provider_name = "fake"

    def __init__(self, fail_geo: str | None = None) -> None:
        self.fail_geo = fail_geo
        self.calls: list[str] = []

    async def search(self, *, marketplace, keyword, geo_profile, device, search_depth):
        self.calls.append(geo_profile.id)
        if geo_profile.id == self.fail_geo:
            raise ProviderUnavailableError("timeout")
        ranks = {
            "ny": {"B0AAA11111": 2, "B0BBB22222": 8},
            "la": {"B0AAA11111": 4, "B0BBB22222": 6},
            "tx": {"B0AAA11111": 6, "B0BBB22222": 4},
        }
        geo_ranks = ranks[geo_profile.id]
        max_rank = max(geo_ranks.values())
        by_rank = {rank: asin for asin, rank in geo_ranks.items()}
        products = []
        for natural_rank in range(1, max_rank + 1):
            asin = by_rank.get(natural_rank, f"FILLER-{geo_profile.id}-{natural_rank}")
            products.append(
                SerpProduct(asin=asin, position=natural_rank + 2, page=1)
            )
        return SerpResult(organic_products=products)


class RecordingRepository:
    def __init__(self) -> None:
        self.run_id = "run-1"
        self.observations = []
        self.snapshots = []
        self.completed = None

    def create_run(self, **kwargs):
        self.created = kwargs
        return self.run_id

    def save_observations(self, run_id, observations):
        assert run_id == self.run_id
        self.observations.extend(observations)

    def save_snapshots(self, run_id, snapshots):
        assert run_id == self.run_id
        self.snapshots.extend(snapshots)

    def complete_run(self, run_id, **kwargs):
        assert run_id == self.run_id
        self.completed = kwargs


def geo(profile_id: str, weight: str) -> GeoProfile:
    return GeoProfile(
        id=profile_id,
        name=profile_id,
        marketplace="amazon.com",
        ip_country="US",
        delivery_country="US",
        delivery_postal_code={"ny": "10001", "la": "90001", "tx": "75201"}[profile_id],
        device="desktop",
        weight=Decimal(weight),
    )


def request() -> RankCheckRequest:
    return RankCheckRequest(
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0AAA11111", "B0BBB22222", "b0aaa11111"],
        geo_profiles=[geo("ny", "30"), geo("la", "40"), geo("tx", "30")],
        search_depth=100,
    )


@pytest.mark.asyncio
async def test_two_asins_across_three_geos_use_three_provider_calls() -> None:
    provider = RecordingProvider()
    repository = RecordingRepository()
    service = RankMonitorService(provider=provider, repository=repository)

    snapshots = await service.check(request())

    assert provider.calls == ["ny", "la", "tx"]
    assert len(repository.observations) == 6
    assert {snapshot.asin for snapshot in snapshots} == {"B0AAA11111", "B0BBB22222"}
    first = next(s for s in snapshots if s.asin == "B0AAA11111")
    second = next(s for s in snapshots if s.asin == "B0BBB22222")
    assert first.weighted_rank == Decimal("4.00")
    assert second.weighted_rank == Decimal("6.00")
    assert repository.completed["status"] == "succeeded"
    assert repository.completed["settled_probe_count"] == 3


@pytest.mark.asyncio
async def test_provider_failure_is_partial_not_not_found() -> None:
    provider = RecordingProvider(fail_geo="la")
    repository = RecordingRepository()
    service = RankMonitorService(provider=provider, repository=repository)

    snapshots = await service.check(request())

    assert len(repository.observations) == 4
    assert all(obs.geo_profile_id != "la" for obs in repository.observations)
    assert repository.completed["status"] == "partially_succeeded"
    assert repository.completed["settled_probe_count"] == 2
    assert "la" in repository.completed["error_summary"]
    assert all(snapshot.confidence == Decimal("0.60") for snapshot in snapshots)


class StrictRecordingProvider(RecordingProvider):
    verification_level = VerificationLevel.STRICT


@pytest.mark.asyncio
async def test_service_preserves_provider_verification_level() -> None:
    provider = StrictRecordingProvider()
    repository = RecordingRepository()
    service = RankMonitorService(provider=provider, repository=repository)

    await service.check(request())

    assert repository.observations
    assert all(
        observation.verification_level == VerificationLevel.STRICT
        for observation in repository.observations
    )
