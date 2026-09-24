from decimal import Decimal

import pytest

from amazon_geo_rank_monitor.domain.errors import RankingError
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    ProbeStatus,
    RankObservation,
    VerificationLevel,
)
from amazon_geo_rank_monitor.ranking.weighted import calculate_weighted_rank


def geo(profile_id: str, weight: str) -> GeoProfile:
    return GeoProfile(
        id=profile_id,
        name=profile_id,
        marketplace="amazon.com",
        ip_country="US",
        delivery_country="US",
        delivery_postal_code="10001",
        device="desktop",
        weight=Decimal(weight),
    )


def obs(asin: str, profile_id: str, rank: int, found: bool = True) -> RankObservation:
    return RankObservation(
        asin=asin,
        geo_profile_id=profile_id,
        provider="test",
        verification_level=VerificationLevel.MANAGED,
        status=ProbeStatus.SUCCESS_FOUND if found else ProbeStatus.SUCCESS_NOT_FOUND,
        found=found,
        organic_rank=rank if found else None,
        effective_rank=rank,
    )


def test_calculates_normalized_weighted_rank() -> None:
    profiles = [geo("ny", "30"), geo("la", "40"), geo("tx", "30")]
    observations = [
        obs("B0TARGET01", "ny", 3),
        obs("B0TARGET01", "la", 5),
        obs("B0TARGET01", "tx", 4),
    ]
    snapshot = calculate_weighted_rank("B0TARGET01", observations, profiles)
    assert snapshot.weighted_rank == Decimal("4.10")
    assert snapshot.found_weight == Decimal("100")
    assert snapshot.missing_weight == Decimal("0")


def test_missing_observation_effective_rank_is_weighted() -> None:
    profiles = [geo("ny", "50"), geo("la", "50")]
    observations = [
        obs("B0TARGET01", "ny", 3),
        obs("B0TARGET01", "la", 101, found=False),
    ]
    snapshot = calculate_weighted_rank("B0TARGET01", observations, profiles)
    assert snapshot.weighted_rank == Decimal("52.00")
    assert snapshot.found_weight == Decimal("50")
    assert snapshot.missing_weight == Decimal("50")


def test_unknown_geo_profile_fails() -> None:
    with pytest.raises(RankingError):
        calculate_weighted_rank(
            "B0TARGET01",
            [obs("B0TARGET01", "unknown", 3)],
            [geo("ny", "100")],
        )
