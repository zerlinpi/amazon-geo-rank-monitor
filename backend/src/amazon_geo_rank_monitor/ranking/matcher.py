from __future__ import annotations

from collections.abc import Iterable

from amazon_geo_rank_monitor.domain.models import (
    ProbeStatus,
    RankObservation,
    SerpProduct,
    SerpResult,
    VerificationLevel,
)


def _index_by_asin(products: Iterable[SerpProduct]) -> dict[str, SerpProduct]:
    indexed: dict[str, SerpProduct] = {}
    for product in products:
        indexed.setdefault(product.asin, product)
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
    """Match requested ASINs against one normalized SERP result."""
    organic = _index_by_asin(result.organic_products)
    sponsored = _index_by_asin(result.sponsored_products)
    absolute = _index_by_asin(result.absolute_products)

    normalized_asins: list[str] = []
    seen: set[str] = set()
    for asin in asins:
        normalized = asin.strip().upper()
        if normalized and normalized not in seen:
            normalized_asins.append(normalized)
            seen.add(normalized)

    observations: list[RankObservation] = []
    for asin in normalized_asins:
        organic_product = organic.get(asin)
        sponsored_product = sponsored.get(asin)
        absolute_product = absolute.get(asin)
        found = organic_product is not None
        organic_rank = organic_product.position if organic_product else None
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
                absolute_rank=absolute_product.position if absolute_product else None,
                sponsored_rank=sponsored_product.position if sponsored_product else None,
                effective_rank=effective_rank,
                page=organic_product.page if organic_product else None,
                raw_result_reference=result.raw_result_reference,
            )
        )
    return observations
