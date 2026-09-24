from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from amazon_geo_rank_monitor.domain.errors import RankingError
from amazon_geo_rank_monitor.domain.models import GeoProfile, RankObservation, RankSnapshot

_TWO_DP = Decimal("0.01")


def calculate_weighted_rank(
    asin: str,
    observations: list[RankObservation],
    geo_profiles: list[GeoProfile],
) -> RankSnapshot:
    """Calculate a weighted organic rank using each observation's effective rank."""
    profile_by_id = {profile.id: profile for profile in geo_profiles}
    relevant = [o for o in observations if o.asin == asin.strip().upper()]
    if not relevant:
        raise RankingError(f"no observations available for ASIN {asin}")

    unknown = sorted({o.geo_profile_id for o in relevant if o.geo_profile_id not in profile_by_id})
    if unknown:
        raise RankingError(f"unknown geo profiles: {', '.join(unknown)}")

    seen_geo: set[str] = set()
    numerator = Decimal("0")
    total_weight = Decimal("0")
    found_weight = Decimal("0")
    missing_weight = Decimal("0")

    for observation in relevant:
        if observation.geo_profile_id in seen_geo:
            raise RankingError(f"duplicate observation for geo profile {observation.geo_profile_id}")
        seen_geo.add(observation.geo_profile_id)
        weight = profile_by_id[observation.geo_profile_id].weight
        total_weight += weight
        numerator += Decimal(observation.effective_rank) * weight
        if observation.found:
            found_weight += weight
        else:
            missing_weight += weight

    if total_weight <= 0:
        raise RankingError("total geo weight must be positive")

    configured_weight = sum((profile.weight for profile in geo_profiles), Decimal("0"))
    if configured_weight <= 0:
        raise RankingError("configured geo weight must be positive")

    weighted_rank = (numerator / total_weight).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
    confidence = (total_weight / configured_weight).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
    return RankSnapshot(
        asin=asin,
        weighted_rank=weighted_rank,
        found_weight=found_weight,
        missing_weight=missing_weight,
        confidence=confidence,
    )
