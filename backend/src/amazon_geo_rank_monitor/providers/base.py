from __future__ import annotations

from typing import Protocol

from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    SerpResult,
    VerificationLevel,
)


class RankProvider(Protocol):
    provider_name: str
    verification_level: VerificationLevel

    async def search(
        self,
        *,
        marketplace: str,
        keyword: str,
        geo_profile: GeoProfile,
        device: str,
        search_depth: int,
    ) -> SerpResult:
        ...
