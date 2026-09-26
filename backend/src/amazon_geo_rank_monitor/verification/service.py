from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.domain.errors import (
    InsufficientCreditsError,
    RankMonitorError,
)
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    RankObservation,
    VerificationLevel,
)
from amazon_geo_rank_monitor.ranking.matcher import match_asins

from .policy import AutoStrictVerificationPolicy

logger = logging.getLogger("amazon_geo_rank_monitor.auto_strict")


@dataclass
class StrictVerificationOutcome:
    requested: bool = False
    attempted: bool = False
    succeeded: bool = False
    cache_hit: bool = False
    triggers: list[str] = field(default_factory=list)
    observations: list[RankObservation] = field(default_factory=list)
    skipped_reason: str | None = None
    error: str | None = None
    upstream_probe_count: int = 0
    cache_hit_count: int = 0

    def as_dict(self, *, geo_profile_id: str) -> dict:
        return {
            "geo_profile_id": geo_profile_id,
            "requested": self.requested,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "cache_hit": self.cache_hit,
            "triggers": list(self.triggers),
            "skipped_reason": self.skipped_reason,
            "error": self.error,
        }


class AutoStrictVerifier:
    def __init__(
        self,
        *,
        policy: AutoStrictVerificationPolicy,
        strict_provider,
        probe_cache=None,
        billing_repository=None,
        rate_card: RateCard | None = None,
    ) -> None:
        self._policy = policy
        self._provider = strict_provider
        self._probe_cache = probe_cache
        self._billing = billing_repository
        self._rate_card = rate_card or RateCard()

    @property
    def enabled(self) -> bool:
        return self._policy.enabled

    async def verify_if_needed(
        self,
        *,
        owner_id: str | None,
        reference_id: str,
        marketplace: str,
        keyword: str,
        geo_profile: GeoProfile,
        search_depth: int,
        asins: list[str],
        managed_result,
        managed_observations: list[RankObservation],
        previous_observations: list[RankObservation],
    ) -> StrictVerificationOutcome:
        triggers = self._policy.evaluate(
            managed_observations=managed_observations,
            previous_observations=previous_observations,
            geo_profile=geo_profile,
            geo_metadata=managed_result.geo_metadata,
        )
        if not triggers:
            return StrictVerificationOutcome()

        outcome = StrictVerificationOutcome(
            requested=True,
            triggers=triggers,
        )
        if not getattr(self._provider, "available", True):
            outcome.skipped_reason = "strict_provider_unavailable"
            return outcome

        cache_hit = None
        if self._probe_cache is not None:
            try:
                cache_hit = self._probe_cache.lookup(
                    owner_id=owner_id,
                    provider_mode="strict",
                    provider=self._provider,
                    marketplace=marketplace,
                    keyword=keyword,
                    geo_profile=geo_profile,
                    search_depth=search_depth,
                )
            except Exception:
                logger.exception(
                    "auto_strict_cache_lookup_failed owner_id=%s geo_profile_id=%s",
                    owner_id,
                    geo_profile.id,
                )

        reservation = None
        if cache_hit is not None:
            strict_result = cache_hit.result
            observed_at = cache_hit.fetched_at
            outcome.cache_hit = True
            outcome.cache_hit_count = 1
        else:
            if self._billing is not None and owner_id is not None:
                idempotency_key = (
                    f"auto_strict:{reference_id}:{geo_profile.id}"
                )
                try:
                    reservation = self._billing.reserve(
                        owner_id=owner_id,
                        credits=self._rate_card.quote("strict", 1),
                        idempotency_key=idempotency_key,
                        reference_type="auto_strict_verification",
                        reference_id=reference_id,
                    )
                except InsufficientCreditsError:
                    outcome.skipped_reason = "insufficient_credits"
                    return outcome

                if reservation["status"] != "reserved":
                    outcome.skipped_reason = (
                        "already_settled"
                        if reservation["status"] == "settled"
                        else "previous_attempt_released"
                    )
                    return outcome

            outcome.attempted = True
            try:
                strict_result = await self._provider.search(
                    marketplace=marketplace,
                    keyword=keyword,
                    geo_profile=geo_profile,
                    device=geo_profile.device,
                    search_depth=search_depth,
                )
            except RankMonitorError as exc:
                if reservation is not None:
                    self._billing.release(reservation["id"])
                outcome.error = str(exc)
                logger.warning(
                    "auto_strict_probe_failed owner_id=%s reference_id=%s geo_profile_id=%s error=%s",
                    owner_id,
                    reference_id,
                    geo_profile.id,
                    exc,
                )
                return outcome

            outcome.upstream_probe_count = 1
            observed_at = datetime.now(UTC)
            if reservation is not None:
                self._billing.settle(
                    reservation["id"],
                    credits_used=self._rate_card.quote("strict", 1),
                )
            if self._probe_cache is not None:
                try:
                    self._probe_cache.store(
                        owner_id=owner_id,
                        provider_mode="strict",
                        provider=self._provider,
                        marketplace=marketplace,
                        keyword=keyword,
                        geo_profile=geo_profile,
                        search_depth=search_depth,
                        result=strict_result,
                    )
                except Exception:
                    logger.exception(
                        "auto_strict_cache_store_failed owner_id=%s geo_profile_id=%s",
                        owner_id,
                        geo_profile.id,
                    )

        provider_name = getattr(
            self._provider,
            "provider_name",
            self._provider.__class__.__name__,
        )
        verification_level = getattr(
            self._provider,
            "verification_level",
            VerificationLevel.STRICT,
        )
        observations = match_asins(
            strict_result,
            asins,
            search_depth=search_depth,
            geo_profile_id=geo_profile.id,
            provider=provider_name,
            verification_level=verification_level,
        )
        if cache_hit is not None:
            observations = [
                observation.model_copy(
                    update={
                        "observed_at": observed_at,
                        "probe_source": "cache",
                        "cache_age_seconds": cache_hit.age_seconds,
                    }
                )
                for observation in observations
            ]
        outcome.observations = observations
        outcome.succeeded = True
        return outcome
