from __future__ import annotations

from typing import Any

from amazon_geo_rank_monitor.domain.errors import RankMonitorError
from amazon_geo_rank_monitor.domain.models import (
    RankCheckRequest,
    RankObservation,
    RankSnapshot,
    VerificationLevel,
)
from amazon_geo_rank_monitor.ranking.matcher import match_asins
from amazon_geo_rank_monitor.ranking.weighted import calculate_weighted_rank


class RankMonitorService:
    """Orchestrate one SERP probe per geo and fan it out to every requested ASIN."""

    def __init__(self, *, provider: Any, repository: Any) -> None:
        self._provider = provider
        self._repository = repository

    async def check(self, request: RankCheckRequest) -> list[RankSnapshot]:
        if not request.geo_profiles:
            raise ValueError("at least one geo profile is required")

        run_id = self._repository.create_run(
            marketplace=request.marketplace,
            keyword=request.keyword,
            requested_probe_count=len(request.geo_profiles),
        )
        observations: list[RankObservation] = []
        errors: list[str] = []
        successful_probe_count = 0

        for geo_profile in request.geo_profiles:
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
            settled_probe_count=successful_probe_count,
            error_summary="; ".join(errors) if errors else None,
        )
        return snapshots
