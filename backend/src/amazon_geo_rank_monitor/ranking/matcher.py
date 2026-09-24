from __future__ import annotations

from collections.abc import Iterable

from amazon_geo_rank_monitor.domain.models import (
    ProbeStatus,
    RankObservation,
    SerpProduct,
    SerpResult,
    VerificationLevel,
)


def _ranked_index_by_asin(
    products: Iterable[SerpProduct],
) -> dict[str, tuple[int, SerpProduct]]:
    indexed: dict[str, tuple[int, SerpProduct]] = {}
    for rank, product in enumerate(products, start=1):
        indexed.setdefault(product.asin, (rank, product))
    return indexed


def match_asins(
    result: SerpResult,
    asins: list[str],
    *,
    search_depth: int,
    geo_profile_id: str,
    provider: str,
    verification_level: VerificationLevel,
) -> list[RankObservation]:
    """Match requested ASINs against one normalized SERP result.

    Provider-reported SerpProduct.position is the mixed SERP position.
    Organic and sponsored ranks are derived from their respective ordered
    collections so ads never inflate the organic rank.
    """
    organic = _ranked_index_by_asin(result.organic_products)
    sponsored = _ranked_index_by_asin(result.sponsored_products)

    normalized_asins: list[str] = []
    seen: set[str] = set()
    for asin in asins:
        normalized = asin.strip().upper()
        if normalized and normalized not in seen:
            normalized_asins.append(normalized)
            seen.add(normalized)

    observations: list[RankObservation] = []
    for asin in normalized_asins:
        organic_match = organic.get(asin)
        sponsored_match = sponsored.get(asin)
        found = organic_match is not None
        organic_rank = organic_match[0] if organic_match else None
        organic_product = organic_match[1] if organic_match else None
        sponsored_rank = sponsored_match[0] if sponsored_match else None
        effective_rank = organic_rank if organic_rank is not None else search_depth + 1

        observations.append(
            RankObservation(
                asin=asin,
                geo_profile_id=geo_profile_id,
                provider=provider,
                verification_level=verification_level,
                status=(
                    ProbeStatus.SUCCESS_FOUND if found else ProbeStatus.SUCCESS_NOT_FOUND
                ),
                found=found,
                organic_rank=organic_rank,
                absolute_rank=organic_product.position if organic_product else None,
                sponsored_rank=sponsored_rank,
                effective_rank=effective_rank,
                page=organic_product.page if organic_product else None,
                raw_result_reference=result.raw_result_reference,
            )
        )
    return observations
