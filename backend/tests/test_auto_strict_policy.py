from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    ProbeStatus,
    RankObservation,
    SerpProduct,
    SerpResult,
    VerificationLevel,
)
from amazon_geo_rank_monitor.verification import (
    AutoStrictVerificationPolicy,
    AutoStrictVerifier,
)


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


def test_low_confidence_trigger_uses_configured_weight_threshold() -> None:
    policy = AutoStrictVerificationPolicy(
        enabled=True,
        min_confidence=Decimal("0.75"),
    )

    assert policy.low_confidence_trigger(
        successful_weight=Decimal("60"),
        total_weight=Decimal("100"),
    ) == "low_confidence:0.60"
    assert policy.low_confidence_trigger(
        successful_weight=Decimal("80"),
        total_weight=Decimal("100"),
    ) is None


def test_monitor_policy_can_disable_but_not_bypass_global_kill_switch() -> None:
    provider = object()
    global_on = AutoStrictVerifier(
        policy=AutoStrictVerificationPolicy(
            enabled=True,
            min_confidence=Decimal("0.75"),
        ),
        strict_provider=provider,
        max_upstream_probes_per_run=3,
    )

    disabled = global_on.for_monitor(
        enabled=False,
        min_confidence="0.90",
        max_upstream_probes_per_run=1,
    )
    assert disabled.enabled is False
    assert disabled.min_confidence == Decimal("0.90")
    assert disabled.max_upstream_probes_per_run == 1

    global_off = AutoStrictVerifier(
        policy=AutoStrictVerificationPolicy(enabled=False),
        strict_provider=provider,
    )
    requested_on = global_off.for_monitor(
        enabled=True,
        min_confidence="0.90",
    )
    assert requested_on.enabled is False


class NeverCalledStrictProvider:
    provider_name = "strict-cache-only"
    verification_level = VerificationLevel.STRICT

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        raise AssertionError("strict provider should not be called")


class StrictCacheHitService:
    def lookup(self, **kwargs):
        return SimpleNamespace(
            result=SerpResult(
                organic_products=[
                    SerpProduct(asin="B0TARGET01", position=3),
                ]
            ),
            fetched_at=datetime.now(UTC),
            age_seconds=2,
        )

    def store(self, **kwargs):
        raise AssertionError("cache store should not be called")


@pytest.mark.asyncio
async def test_exhausted_probe_budget_still_allows_strict_cache_hits() -> None:
    provider = NeverCalledStrictProvider()
    verifier = AutoStrictVerifier(
        policy=AutoStrictVerificationPolicy(enabled=True),
        strict_provider=provider,
        probe_cache=StrictCacheHitService(),
        max_upstream_probes_per_run=0,
    )

    outcome = await verifier.verify_for_triggers(
        owner_id="tenant-1",
        reference_id="run-1",
        marketplace="amazon.com",
        keyword="walking pad",
        geo_profile=geo(),
        search_depth=100,
        asins=["B0TARGET01"],
        triggers=["rank_movement:B0TARGET01:25"],
        allow_upstream=False,
    )

    assert outcome.succeeded is True
    assert outcome.cache_hit is True
    assert outcome.cache_hit_count == 1
    assert outcome.upstream_probe_count == 0
    assert provider.calls == 0
