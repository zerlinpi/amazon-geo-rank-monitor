from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from amazon_geo_rank_monitor.domain.errors import RankMonitorError
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    RankCheckRequest,
    RankExecutionResult,
    RankObservation,
    RankSnapshot,
    VerificationLevel,
)
from amazon_geo_rank_monitor.ranking.matcher import match_asins
from amazon_geo_rank_monitor.ranking.weighted import calculate_weighted_rank

logger = logging.getLogger("amazon_geo_rank_monitor.rank")


class RankMonitorService:
    """Orchestrate one SERP probe per geo and fan it out to every requested ASIN."""

    def __init__(
        self,
        *,
        provider: Any,
        repository: Any,
        probe_cache=None,
        provider_mode: str | None = None,
        competitive_intelligence=None,
        strict_verifier=None,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._probe_cache = probe_cache
        self._provider_mode = provider_mode
        self._competitive_intelligence = competitive_intelligence
        self._strict_verifier = strict_verifier

    async def check(self, request: RankCheckRequest) -> list[RankSnapshot]:
        return (await self.check_with_result(request)).snapshots

    async def check_with_result(
        self,
        request: RankCheckRequest,
        *,
        owner_id: str | None = None,
        prepared_cache: dict[str, Any] | None = None,
        verification_reference_id: str | None = None,
        force_strict_verification: bool = False,
    ) -> RankExecutionResult:
        if not request.geo_profiles:
            raise ValueError("at least one geo profile is required")

        run_id = self._repository.create_run(
            marketplace=request.marketplace,
            keyword=request.keyword,
            requested_probe_count=len(request.geo_profiles),
            owner_id=owner_id,
        )
        observations: list[RankObservation] = []
        preferred_observations: list[RankObservation] = []
        errors: list[str] = []
        verification_events: list[dict] = []
        successful_probe_count = 0
        primary_upstream_probe_count = 0
        primary_cache_hit_count = 0
        strict_upstream_probe_count = 0
        strict_upstream_attempt_count = 0
        strict_cache_hit_count = 0
        strict_probe_budget = (
            self._strict_verifier.max_upstream_probes_per_run
            if self._strict_verifier is not None
            and hasattr(self._strict_verifier, "max_upstream_probes_per_run")
            else None
        )
        failed_geo_profiles: list[GeoProfile] = []
        successful_geo_ids: set[str] = set()

        prepared_cache = prepared_cache or {}
        for geo_profile in request.geo_profiles:
            cache_hit = prepared_cache.get(geo_profile.id)
            if (
                cache_hit is None
                and self._probe_cache is not None
                and self._provider_mode is not None
            ):
                try:
                    cache_hit = self._probe_cache.lookup(
                        owner_id=owner_id,
                        provider_mode=self._provider_mode,
                        provider=self._provider,
                        marketplace=request.marketplace,
                        keyword=request.keyword,
                        geo_profile=geo_profile,
                        search_depth=request.search_depth,
                    )
                except Exception:
                    logger.exception(
                        "probe_cache_lookup_failed owner_id=%s geo_profile_id=%s",
                        owner_id,
                        geo_profile.id,
                    )

            if cache_hit is not None:
                result = cache_hit.result
                primary_cache_hit_count += 1
            else:
                try:
                    result = await self._provider.search(
                        marketplace=request.marketplace,
                        keyword=request.keyword,
                        geo_profile=geo_profile,
                        device=geo_profile.device,
                        search_depth=request.search_depth,
                    )
                except RankMonitorError as exc:
                    errors.append(f"{geo_profile.id}: {exc}")
                    failed_geo_profiles.append(geo_profile)
                    continue
                primary_upstream_probe_count += 1
                if self._probe_cache is not None and self._provider_mode is not None:
                    try:
                        self._probe_cache.store(
                            owner_id=owner_id,
                            provider_mode=self._provider_mode,
                            provider=self._provider,
                            marketplace=request.marketplace,
                            keyword=request.keyword,
                            geo_profile=geo_profile,
                            search_depth=request.search_depth,
                            result=result,
                        )
                    except Exception:
                        logger.exception(
                            "probe_cache_store_failed owner_id=%s geo_profile_id=%s",
                            owner_id,
                            geo_profile.id,
                        )

            observed_at = (
                cache_hit.fetched_at
                if cache_hit is not None
                else datetime.now(UTC)
            )
            if self._competitive_intelligence is not None:
                try:
                    self._competitive_intelligence.capture_probe(
                        owner_id=owner_id,
                        run_id=run_id,
                        geo_profile_id=geo_profile.id,
                        result=result,
                        search_depth=request.search_depth,
                        probe_source=(
                            "cache" if cache_hit is not None else "upstream"
                        ),
                        cache_age_seconds=(
                            cache_hit.age_seconds
                            if cache_hit is not None
                            else None
                        ),
                        observed_at=observed_at,
                    )
                except Exception:
                    logger.exception(
                        "competitive_capture_failed owner_id=%s run_id=%s geo_profile_id=%s",
                        owner_id,
                        run_id,
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
                VerificationLevel.MANAGED,
            )
            geo_observations = match_asins(
                result,
                request.asins,
                search_depth=request.search_depth,
                geo_profile_id=geo_profile.id,
                provider=provider_name,
                verification_level=verification_level,
            )
            if cache_hit is not None:
                geo_observations = [
                    observation.model_copy(
                        update={
                            "observed_at": cache_hit.fetched_at,
                            "probe_source": "cache",
                            "cache_age_seconds": cache_hit.age_seconds,
                        }
                    )
                    for observation in geo_observations
                ]

            persisted_geo_observations = list(geo_observations)
            preferred_geo_observations = list(geo_observations)

            if (
                self._provider_mode == "managed"
                and self._strict_verifier is not None
                and (
                    getattr(self._strict_verifier, "enabled", False)
                    or force_strict_verification
                )
            ):
                previous_observations: list[RankObservation] = []
                if hasattr(self._repository, "previous_observations"):
                    try:
                        previous_observations = (
                            self._repository.previous_observations(
                                owner_id=owner_id,
                                marketplace=request.marketplace,
                                keyword=request.keyword,
                                geo_profile_id=geo_profile.id,
                                exclude_run_id=run_id,
                            )
                        )
                    except Exception:
                        logger.exception(
                            "auto_strict_history_lookup_failed "
                            "owner_id=%s run_id=%s geo_profile_id=%s",
                            owner_id,
                            run_id,
                            geo_profile.id,
                        )

                outcome = await self._strict_verifier.verify_if_needed(
                    owner_id=owner_id,
                    reference_id=verification_reference_id or run_id,
                    marketplace=request.marketplace,
                    keyword=request.keyword,
                    geo_profile=geo_profile,
                    search_depth=request.search_depth,
                    asins=request.asins,
                    managed_result=result,
                    managed_observations=geo_observations,
                    previous_observations=previous_observations,
                    allow_upstream=(
                        strict_probe_budget is None
                        or strict_upstream_attempt_count < strict_probe_budget
                    ),
                    force_strict=force_strict_verification,
                )
                if outcome.requested:
                    verification_events.append(
                        outcome.as_dict(geo_profile_id=geo_profile.id)
                    )
                strict_upstream_probe_count += outcome.upstream_probe_count
                strict_upstream_attempt_count += int(outcome.attempted)
                strict_cache_hit_count += outcome.cache_hit_count
                if outcome.observations:
                    persisted_geo_observations.extend(outcome.observations)
                    if outcome.succeeded:
                        preferred_geo_observations = list(outcome.observations)
                if outcome.error:
                    errors.append(
                        f"strict:{geo_profile.id}: {outcome.error}"
                    )

            self._repository.save_observations(
                run_id,
                persisted_geo_observations,
            )
            observations.extend(persisted_geo_observations)
            preferred_observations.extend(preferred_geo_observations)
            successful_probe_count += 1
            successful_geo_ids.add(geo_profile.id)

        if (
            self._provider_mode == "managed"
            and self._strict_verifier is not None
            and (
                getattr(self._strict_verifier, "enabled", False)
                or force_strict_verification
            )
            and failed_geo_profiles
        ):
            total_weight = sum(
                (profile.weight for profile in request.geo_profiles),
                start=0,
            )
            successful_weight = sum(
                (
                    profile.weight
                    for profile in request.geo_profiles
                    if profile.id in successful_geo_ids
                ),
                start=0,
            )
            confidence_trigger = self._strict_verifier.low_confidence_trigger(
                successful_weight=successful_weight,
                total_weight=total_weight,
            )
            recovery_triggers: list[str] = []
            if force_strict_verification:
                recovery_triggers.append("manual_force")
            if confidence_trigger is not None:
                recovery_triggers.append(confidence_trigger)
            if recovery_triggers:
                for geo_profile in failed_geo_profiles:
                    outcome = await self._strict_verifier.verify_for_triggers(
                        owner_id=owner_id,
                        reference_id=verification_reference_id or run_id,
                        marketplace=request.marketplace,
                        keyword=request.keyword,
                        geo_profile=geo_profile,
                        search_depth=request.search_depth,
                        asins=request.asins,
                        triggers=[
                            *recovery_triggers,
                            "managed_probe_failed",
                        ],
                        allow_upstream=(
                            strict_probe_budget is None
                            or strict_upstream_attempt_count < strict_probe_budget
                        ),
                    )
                    if outcome.requested:
                        verification_events.append(
                            outcome.as_dict(geo_profile_id=geo_profile.id)
                        )
                    strict_upstream_probe_count += outcome.upstream_probe_count
                    strict_upstream_attempt_count += int(outcome.attempted)
                    strict_cache_hit_count += outcome.cache_hit_count
                    if outcome.observations:
                        self._repository.save_observations(
                            run_id,
                            outcome.observations,
                        )
                        observations.extend(outcome.observations)
                        preferred_observations.extend(outcome.observations)
                        if outcome.succeeded:
                            successful_probe_count += 1
                            successful_geo_ids.add(geo_profile.id)
                    if outcome.error:
                        errors.append(
                            f"strict:{geo_profile.id}: {outcome.error}"
                        )

        snapshots: list[RankSnapshot] = []
        if successful_probe_count:
            for asin in request.asins:
                asin_observations = [
                    obs for obs in preferred_observations if obs.asin == asin
                ]
                if not asin_observations:
                    continue
                snapshots.append(
                    calculate_weighted_rank(
                        asin,
                        asin_observations,
                        request.geo_profiles,
                    )
                )
            if snapshots:
                self._repository.save_snapshots(run_id, snapshots)

        if successful_probe_count == len(request.geo_profiles):
            status = "succeeded"
        elif successful_probe_count == 0:
            status = "failed"
        else:
            status = "partially_succeeded"

        upstream_probe_count = (
            primary_upstream_probe_count + strict_upstream_probe_count
        )
        cache_hit_count = primary_cache_hit_count + strict_cache_hit_count
        verification_metadata = {
            "manual_force_requested": bool(
                self._provider_mode == "managed"
                and force_strict_verification
            ),
            "manual_force_effective": bool(
                self._provider_mode == "managed"
                and force_strict_verification
                and self._strict_verifier is not None
                and getattr(self._strict_verifier, "enabled", False)
            ),
            "auto_strict_enabled": bool(
                self._provider_mode == "managed"
                and self._strict_verifier is not None
                and getattr(self._strict_verifier, "enabled", False)
            ),
            "auto_strict_min_confidence": (
                str(self._strict_verifier.min_confidence)
                if self._strict_verifier is not None
                and hasattr(self._strict_verifier, "min_confidence")
                else None
            ),
            "auto_strict_max_upstream_probes_per_run": strict_probe_budget,
            "strict_upstream_attempt_count": strict_upstream_attempt_count,
            "strict_requested_count": len(verification_events),
            "strict_attempted_count": sum(
                1 for item in verification_events if item.get("attempted")
            ),
            "strict_succeeded_count": sum(
                1 for item in verification_events if item.get("succeeded")
            ),
            "strict_skipped_count": sum(
                1
                for item in verification_events
                if item.get("skipped_reason") is not None
            ),
            "events": verification_events,
        }
        self._repository.complete_run(
            run_id,
            status=status,
            settled_probe_count=upstream_probe_count,
            cache_hit_count=cache_hit_count,
            verification_metadata=verification_metadata,
            error_summary="; ".join(errors) if errors else None,
        )
        return RankExecutionResult(
            run_id=run_id,
            status=status,
            observations=observations,
            snapshots=snapshots,
            errors=errors,
            requested_probe_count=len(request.geo_profiles),
            upstream_probe_count=upstream_probe_count,
            cache_hit_count=cache_hit_count,
            primary_upstream_probe_count=primary_upstream_probe_count,
            primary_cache_hit_count=primary_cache_hit_count,
            strict_verification_upstream_probe_count=strict_upstream_probe_count,
            strict_verification_cache_hit_count=strict_cache_hit_count,
            verification_events=verification_events,
        )
