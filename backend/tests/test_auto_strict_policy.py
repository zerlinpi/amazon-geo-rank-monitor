from decimal import Decimal

from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    ProbeStatus,
    RankObservation,
    VerificationLevel,
)
from amazon_geo_rank_monitor.verification import AutoStrictVerificationPolicy


def geo() -> GeoProfile:
    return GeoProfile(
        id="ny",
        name="New York",
        marketplace="amazon.com",
        ip_country="US",
        ip_postal_code="10001",
        delivery_country="US",
        delivery_postal_code="10001",
        weight=Decimal("1"),
    )


def observation(
    *,
    asin: str = "B0TARGET01",
    found: bool = True,
    effective_rank: int = 10,
) -> RankObservation:
    return RankObservation(
        asin=asin,
        geo_profile_id="ny",
        provider="fake",
        verification_level=VerificationLevel.MANAGED,
        status=(
            ProbeStatus.SUCCESS_FOUND
            if found
            else ProbeStatus.SUCCESS_NOT_FOUND
        ),
        found=found,
        organic_rank=effective_rank if found else None,
        absolute_rank=effective_rank if found else None,
        effective_rank=effective_rank,
        page=1 if found else None,
    )


def test_disabled_policy_never_escalates() -> None:
    policy = AutoStrictVerificationPolicy(enabled=False)
    assert policy.evaluate(
        managed_observations=[observation(effective_rank=50)],
        previous_observations=[observation(effective_rank=5)],
        geo_profile=geo(),
        geo_metadata={},
    ) == []


def test_large_rank_movement_triggers_strict_verification() -> None:
    policy = AutoStrictVerificationPolicy(
        enabled=True,
        rank_delta_threshold=20,
    )
    reasons = policy.evaluate(
        managed_observations=[observation(effective_rank=31)],
        previous_observations=[observation(effective_rank=5)],
        geo_profile=geo(),
        geo_metadata={},
    )
    assert reasons == ["rank_movement:B0TARGET01:26"]


def test_not_found_after_found_triggers_strict_verification() -> None:
    policy = AutoStrictVerificationPolicy(enabled=True)
    reasons = policy.evaluate(
        managed_observations=[observation(found=False, effective_rank=101)],
        previous_observations=[observation(found=True, effective_rank=7)],
        geo_profile=geo(),
        geo_metadata={},
    )
    assert reasons == ["not_found_after_found:B0TARGET01"]


def test_explicit_geo_mismatch_triggers_strict_verification() -> None:
    policy = AutoStrictVerificationPolicy(enabled=True)
    reasons = policy.evaluate(
        managed_observations=[observation()],
        previous_observations=[],
        geo_profile=geo(),
        geo_metadata={
            "observed_ip_country": "CA",
            "observed_ip_postal_code": "M5V",
            "confirmed_delivery_postal_code": "90210",
        },
    )
    assert reasons == [
        "geo_country_mismatch",
        "geo_postal_mismatch",
        "delivery_postal_mismatch",
    ]
