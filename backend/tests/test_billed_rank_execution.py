from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.application.rank_application import execute_rank_check
from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.domain.errors import (
    InsufficientCreditsError,
    ProviderUnavailableError,
)
from amazon_geo_rank_monitor.domain.models import GeoProfile, SerpProduct, SerpResult
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.models import Base, TenantRow
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.verification import (
    AutoStrictVerificationPolicy,
    AutoStrictVerifier,
)


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


def make_services(
    provider,
    *,
    strict_provider=None,
    auto_strict=False,
    strict_probe_budget=None,
):
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
    rate_card = RateCard(managed_serp=1, browser_verified_serp=5)
    registry = ProviderRegistry(
        managed=provider,
        strict=strict_provider or provider,
    )
    services = AppServices(
        tenant_repository=None,
        geo_repository=geo,
        monitor_repository=None,
        job_repository=None,
        rank_repository=RankRepository(engine),
        api_keys=None,
        provider_registry=registry,
        billing_repository=billing,
        rate_card=rate_card,
    )
    if auto_strict:
        services.auto_strict_verifier = AutoStrictVerifier(
            policy=AutoStrictVerificationPolicy(
                enabled=True,
                rank_delta_threshold=20,
            ),
            strict_provider=registry.get("strict"),
            billing_repository=billing,
            rate_card=rate_card,
            max_upstream_probes_per_run=strict_probe_budget,
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


class MultiFailProvider:
    provider_name = "managed-multi-fail"

    def __init__(self, fail_zips: set[str] | None = None) -> None:
        self.fail_zips = fail_zips or set()
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        geo = kwargs["geo_profile"]
        if geo.delivery_postal_code in self.fail_zips:
            raise ProviderUnavailableError("timeout")
        return SerpResult(
            organic_products=[SerpProduct(asin="B0TARGET01", position=4)]
        )


class SequenceRankProvider:
    provider_name = "managed-sequence"

    def __init__(self, ranks: list[int]) -> None:
        self.ranks = list(ranks)
        self.calls = 0

    async def search(self, **kwargs):
        rank = self.ranks[min(self.calls, len(self.ranks) - 1)]
        self.calls += 1
        products = [
            SerpProduct(asin=f"FILLER{i:03d}", position=i)
            for i in range(1, rank)
        ]
        products.append(SerpProduct(asin="B0TARGET01", position=rank))
        return SerpResult(organic_products=products)


@pytest.mark.asyncio
async def test_auto_strict_escalation_uses_strict_result_and_bills_separately() -> None:
    managed = SequenceRankProvider([5, 40])
    strict = SequenceRankProvider([7])
    services, geo, billing = make_services(
        managed,
        strict_provider=strict,
        auto_strict=True,
    )
    ny = add_geo(geo, "ny", "10001")
    billing.grant(
        owner_id="tenant-1",
        credits=20,
        idempotency_key="grant:auto-strict",
    )

    first = await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[ny["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="auto-strict-first",
    )
    second = await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[ny["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="auto-strict-second",
    )

    assert first.strict_verification_upstream_probe_count == 0
    assert second.primary_upstream_probe_count == 1
    assert second.strict_verification_upstream_probe_count == 1
    assert second.upstream_probe_count == 2
    assert second.snapshots[0].weighted_rank == Decimal("7.00")
    assert {item.verification_level.value for item in second.observations} == {
        "managed",
        "strict",
    }
    assert second.verification_events[0]["succeeded"] is True
    saved = services.rank_repository.get_run(
        second.run_id,
        owner_id="tenant-1",
    )
    assert saved["verification_metadata"]["strict_succeeded_count"] == 1
    assert saved["verification_metadata"]["events"][0]["succeeded"] is True
    assert strict.calls == 1
    assert billing.get_balance("tenant-1") == {
        "balance": 13,
        "reserved": 0,
        "available": 13,
    }


@pytest.mark.asyncio
async def test_auto_strict_insufficient_credits_keeps_managed_result() -> None:
    managed = SequenceRankProvider([5, 40])
    strict = SequenceRankProvider([7])
    services, geo, billing = make_services(
        managed,
        strict_provider=strict,
        auto_strict=True,
    )
    ny = add_geo(geo, "ny", "10001")
    billing.grant(
        owner_id="tenant-1",
        credits=2,
        idempotency_key="grant:auto-strict-low-balance",
    )

    await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[ny["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="auto-strict-low-first",
    )
    second = await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[ny["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="auto-strict-low-second",
    )

    assert second.status == "succeeded"
    assert second.strict_verification_upstream_probe_count == 0
    assert second.snapshots[0].weighted_rank == Decimal("40.00")
    assert second.verification_events[0]["skipped_reason"] == "insufficient_credits"
    assert strict.calls == 0
    assert billing.get_balance("tenant-1") == {
        "balance": 0,
        "reserved": 0,
        "available": 0,
    }


class FailingStrictProvider:
    provider_name = "strict-failing"

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        raise ProviderUnavailableError("strict browser unavailable")


@pytest.mark.asyncio
async def test_auto_strict_failure_preserves_managed_success_and_releases_credits() -> None:
    managed = SequenceRankProvider([5, 40])
    strict = FailingStrictProvider()
    services, geo, billing = make_services(
        managed,
        strict_provider=strict,
        auto_strict=True,
    )
    ny = add_geo(geo, "ny", "10001")
    billing.grant(
        owner_id="tenant-1",
        credits=10,
        idempotency_key="grant:auto-strict-failure",
    )

    await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[ny["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="auto-strict-failure-first",
    )
    second = await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[ny["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="auto-strict-failure-second",
    )

    assert second.status == "succeeded"
    assert second.strict_verification_upstream_probe_count == 0
    assert second.snapshots[0].weighted_rank == Decimal("40.00")
    assert second.verification_events[0]["attempted"] is True
    assert second.verification_events[0]["succeeded"] is False
    assert "strict browser unavailable" in second.verification_events[0]["error"]
    assert strict.calls == 1
    assert billing.get_balance("tenant-1") == {
        "balance": 8,
        "reserved": 0,
        "available": 8,
    }


@pytest.mark.asyncio
async def test_low_confidence_recovers_failed_geo_with_billed_strict_probe() -> None:
    managed = CountingProvider(fail_zip="90001")
    strict = CountingProvider()
    services, geo, billing = make_services(
        managed,
        strict_provider=strict,
        auto_strict=True,
    )
    ny = add_geo(geo, "ny", "10001")
    la = add_geo(geo, "la", "90001")
    billing.grant(
        owner_id="tenant-1",
        credits=20,
        idempotency_key="grant:low-confidence-recovery",
    )

    result = await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[ny["id"], la["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="low-confidence-recovery",
    )

    assert result.status == "succeeded"
    assert result.primary_upstream_probe_count == 1
    assert result.strict_verification_upstream_probe_count == 1
    assert result.snapshots[0].confidence == Decimal("1.00")
    assert {
        (item.geo_profile_id, item.verification_level.value)
        for item in result.observations
    } == {
        (ny["id"], "managed"),
        (la["id"], "strict"),
    }
    assert "low_confidence:0.50" in result.verification_events[0]["triggers"]
    assert "managed_probe_failed" in result.verification_events[0]["triggers"]
    assert result.verification_events[0]["succeeded"] is True
    assert billing.get_balance("tenant-1") == {
        "balance": 14,
        "reserved": 0,
        "available": 14,
    }


@pytest.mark.asyncio
async def test_strict_probe_budget_caps_upstream_attempts_and_credit_spend() -> None:
    managed = MultiFailProvider(fail_zips={"90001", "75201"})
    strict = MultiFailProvider()
    services, geo, billing = make_services(
        managed,
        strict_provider=strict,
        auto_strict=True,
        strict_probe_budget=1,
    )
    ny = add_geo(geo, "ny", "10001")
    la = add_geo(geo, "la", "90001")
    tx = add_geo(geo, "tx", "75201")
    billing.grant(
        owner_id="tenant-1",
        credits=20,
        idempotency_key="grant:strict-budget",
    )

    result = await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[ny["id"], la["id"], tx["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="strict-budget",
    )

    assert result.status == "partially_succeeded"
    assert result.primary_upstream_probe_count == 1
    assert result.strict_verification_upstream_probe_count == 1
    assert strict.calls == 1
    assert result.snapshots[0].confidence == Decimal("0.67")
    assert len(result.verification_events) == 2
    assert result.verification_events[0]["succeeded"] is True
    assert (
        result.verification_events[1]["skipped_reason"]
        == "probe_budget_exhausted"
    )
    saved = services.rank_repository.get_run(
        result.run_id,
        owner_id="tenant-1",
    )
    assert (
        saved["verification_metadata"][
            "auto_strict_max_upstream_probes_per_run"
        ]
        == 1
    )
    assert saved["verification_metadata"]["strict_upstream_attempt_count"] == 1
    assert billing.get_balance("tenant-1") == {
        "balance": 14,
        "reserved": 0,
        "available": 14,
    }


@pytest.mark.asyncio
async def test_manual_force_verifies_stable_managed_result_and_bills_strict() -> None:
    managed = SequenceRankProvider([5])
    strict = SequenceRankProvider([7])
    services, geo, billing = make_services(
        managed,
        strict_provider=strict,
        auto_strict=True,
        strict_probe_budget=1,
    )
    ny = add_geo(geo, "ny", "10001")
    billing.grant(
        owner_id="tenant-1",
        credits=10,
        idempotency_key="grant:manual-force",
    )

    result = await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[ny["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="manual-force",
        force_strict_verification=True,
    )

    assert result.status == "succeeded"
    assert managed.calls == 1
    assert strict.calls == 1
    assert result.primary_upstream_probe_count == 1
    assert result.strict_verification_upstream_probe_count == 1
    assert result.snapshots[0].weighted_rank == Decimal("7.00")
    assert result.verification_events[0]["triggers"] == ["manual_force"]
    assert result.verification_events[0]["succeeded"] is True

    saved = services.rank_repository.get_run(
        result.run_id,
        owner_id="tenant-1",
    )
    assert saved["verification_metadata"]["manual_force_requested"] is True
    assert saved["verification_metadata"]["manual_force_effective"] is True
    assert saved["verification_metadata"]["auto_strict_enabled"] is True
    assert billing.get_balance("tenant-1") == {
        "balance": 4,
        "reserved": 0,
        "available": 4,
    }


@pytest.mark.asyncio
async def test_manual_force_recovers_managed_failure_with_strict_probe() -> None:
    managed = CountingProvider(fail_zip="90001")
    strict = CountingProvider()
    services, geo, billing = make_services(
        managed,
        strict_provider=strict,
        auto_strict=True,
        strict_probe_budget=1,
    )
    la = add_geo(geo, "la", "90001")
    billing.grant(
        owner_id="tenant-1",
        credits=10,
        idempotency_key="grant:manual-force-recovery",
    )

    result = await execute_rank_check(
        services=services,
        owner_id="tenant-1",
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0TARGET01"],
        geo_profile_ids=[la["id"]],
        search_depth=100,
        provider_mode="managed",
        reference_id="manual-force-recovery",
        force_strict_verification=True,
    )

    assert result.status == "succeeded"
    assert result.primary_upstream_probe_count == 0
    assert result.strict_verification_upstream_probe_count == 1
    assert result.snapshots[0].confidence == Decimal("1.00")
    assert "manual_force" in result.verification_events[0]["triggers"]
    assert "managed_probe_failed" in result.verification_events[0]["triggers"]
    assert strict.calls == 1
    assert billing.get_balance("tenant-1") == {
        "balance": 5,
        "reserved": 0,
        "available": 5,
    }
