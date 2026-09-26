from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from amazon_geo_rank_monitor.domain.errors import RankMonitorError
from amazon_geo_rank_monitor.domain.models import (
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
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._probe_cache = probe_cache
        self._provider_mode = provider_mode
        self._competitive_intelligence = competitive_intelligence

    async def check(self, request: RankCheckRequest) -> list[RankSnapshot]:
        return (await self.check_with_result(request)).snapshots

    async def check_with_result(
        self,
        request: RankCheckRequest,
        *,
        owner_id: str | None = None,
        prepared_cache: dict[str, Any] | None = None,
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
        errors: list[str] = []
        successful_probe_count = 0
        upstream_probe_count = 0
        cache_hit_count = 0

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
                cache_hit_count += 1
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
                    continue
                upstream_probe_count += 1
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
            self._repository.save_observations(run_id, geo_observations)
            observations.extend(geo_observations)
            successful_probe_count += 1

        snapshots: list[RankSnapshot] = []
        if successful_probe_count:
            for asin in request.asins:
                asin_observations = [obs for obs in observations if obs.asin == asin]
                if not asin_observations:
                    continue
                snapshots.append(
                    calculate_weighted_rank(asin, asin_observations, request.geo_profiles)
                )
            if snapshots:
                self._repository.save_snapshots(run_id, snapshots)

        if successful_probe_count == len(request.geo_profiles):
            status = "succeeded"
        elif successful_probe_count == 0:
            status = "failed"
        else:
            status = "partially_succeeded"

        self._repository.complete_run(
            run_id,
            status=status,
            settled_probe_count=upstream_probe_count,
            cache_hit_count=cache_hit_count,
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
        )
