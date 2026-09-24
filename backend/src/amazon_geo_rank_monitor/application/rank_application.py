from __future__ import annotations

from uuid import uuid4

from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.domain.models import RankCheckRequest
from amazon_geo_rank_monitor.monitor.service import RankMonitorService


def build_rank_request(
    *,
    geo_repository,
    owner_id: str,
    marketplace: str,
    keyword: str,
    asins: list[str],
    geo_profile_ids: list[str],
    search_depth: int,
) -> RankCheckRequest:
    profiles = []
    for profile_id in geo_profile_ids:
        profile = geo_repository.get_domain(profile_id, owner_id=owner_id)
        if profile is None:
            raise KeyError(f"geo profile not found: {profile_id}")
        profiles.append(profile)
    return RankCheckRequest(
        marketplace=marketplace,
        keyword=keyword,
        asins=asins,
        geo_profiles=profiles,
        search_depth=search_depth,
    )


async def execute_rank_check(
    *,
    services,
    owner_id: str,
    marketplace: str,
    keyword: str,
    asins: list[str],
    geo_profile_ids: list[str],
    search_depth: int,
    provider_mode: str,
    reference_id: str | None = None,
):
    request = build_rank_request(
        geo_repository=services.geo_repository,
        owner_id=owner_id,
        marketplace=marketplace,
        keyword=keyword,
        asins=asins,
        geo_profile_ids=geo_profile_ids,
        search_depth=search_depth,
    )
    provider = services.provider_registry.get(provider_mode)
    service = RankMonitorService(
        provider=provider,
        repository=services.rank_repository,
    )

    billing = getattr(services, "billing_repository", None)
    rate_card = getattr(services, "rate_card", None) or RateCard()
    reservation = None
    if billing is not None:
        reference_id = reference_id or uuid4().hex
        reservation = billing.reserve(
            owner_id=owner_id,
            credits=rate_card.quote(provider_mode, len(request.geo_profiles)),
            idempotency_key=f"rank_check:{reference_id}",
            reference_type="rank_check",
            reference_id=reference_id,
        )

    try:
        result = await service.check_with_result(request, owner_id=owner_id)
    except Exception:
        if reservation is not None:
            billing.release(reservation["id"])
        raise

    if reservation is not None:
        successful_geos = len({item.geo_profile_id for item in result.observations})
        billing.settle(
            reservation["id"],
            credits_used=rate_card.quote(provider_mode, successful_geos),
        )
    return result


def enqueue_monitor(*, services, owner_id: str, monitor: dict) -> dict:
    request = build_rank_request(
        geo_repository=services.geo_repository,
        owner_id=owner_id,
        marketplace=monitor["marketplace"],
        keyword=monitor["keyword"],
        asins=monitor["asins"],
        geo_profile_ids=monitor["geo_profile_ids"],
        search_depth=monitor["search_depth"],
    )
    return services.job_repository.enqueue(
        owner_id=owner_id,
        monitor_target_id=monitor["id"],
        provider_mode=monitor["provider_mode"],
        request_payload=request.model_dump(mode="json"),
    )


def serialize_execution_result(result) -> dict:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "errors": result.errors,
        "observations": [
            item.model_dump(mode="json") for item in result.observations
        ],
        "snapshots": [
            {
                **item.model_dump(mode="json"),
                "weighted_rank": str(item.weighted_rank),
                "found_weight": str(item.found_weight),
                "missing_weight": str(item.missing_weight),
                "confidence": str(item.confidence),
            }
            for item in result.snapshots
        ],
    }
