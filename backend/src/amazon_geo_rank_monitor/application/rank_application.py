from __future__ import annotations

import logging
from uuid import uuid4

from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.domain.models import RankCheckRequest
from amazon_geo_rank_monitor.monitor.service import RankMonitorService

logger = logging.getLogger("amazon_geo_rank_monitor.rank_application")


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
    reference_id = reference_id or uuid4().hex
    prepared_cache = {}
    probe_cache = getattr(services, "probe_cache", None)
    if probe_cache is not None:
        try:
            prepared_cache = probe_cache.prefetch(
                owner_id=owner_id,
                provider_mode=provider_mode,
                provider=provider,
                request=request,
            )
        except Exception:
            logger.exception(
                "probe_cache_prefetch_failed owner_id=%s provider_mode=%s",
                owner_id,
                provider_mode,
            )
    service = RankMonitorService(
        provider=provider,
        repository=services.rank_repository,
        probe_cache=getattr(services, "probe_cache", None),
        provider_mode=provider_mode,
        competitive_intelligence=getattr(
            services,
            "competitive_intelligence",
            None,
        ),
        strict_verifier=getattr(services, "auto_strict_verifier", None),
    )

    billing = getattr(services, "billing_repository", None)
    rate_card = getattr(services, "rate_card", None) or RateCard()
    reservation = None
    reserve_probe_count = max(
        len(request.geo_profiles) - len(prepared_cache),
        0,
    )
    if billing is not None and reserve_probe_count > 0:
        reservation = billing.reserve(
            owner_id=owner_id,
            credits=rate_card.quote(provider_mode, reserve_probe_count),
            idempotency_key=f"rank_check:{reference_id}",
            reference_type="rank_check",
            reference_id=reference_id,
        )

    try:
        result = await service.check_with_result(
            request,
            owner_id=owner_id,
            prepared_cache=prepared_cache,
            verification_reference_id=reference_id,
        )
    except Exception:
        if reservation is not None:
            billing.release(reservation["id"])
        raise

    if reservation is not None:
        billing.settle(
            reservation["id"],
            credits_used=rate_card.quote(
                provider_mode,
                result.primary_upstream_probe_count,
            ),
        )
    return result


def enqueue_monitor(
    *,
    services,
    owner_id: str,
    monitor: dict,
    job_id: str | None = None,
) -> dict:
    request = build_rank_request(
        geo_repository=services.geo_repository,
        owner_id=owner_id,
        marketplace=monitor["marketplace"],
        keyword=monitor["keyword"],
        asins=monitor["asins"],
        geo_profile_ids=monitor["geo_profile_ids"],
        search_depth=monitor["search_depth"],
    )
    request_payload = request.model_dump(mode="json")
    confidence = monitor.get("auto_strict_min_confidence")
    request_payload["_verification_policy"] = {
        "enabled": monitor.get("auto_strict_enabled"),
        "min_confidence": (
            str(confidence)
            if confidence is not None
            else None
        ),
    }
    return services.job_repository.enqueue(
        owner_id=owner_id,
        monitor_target_id=monitor["id"],
        provider_mode=monitor["provider_mode"],
        request_payload=request_payload,
        job_id=job_id,
    )


def serialize_execution_result(result) -> dict:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "errors": result.errors,
        "usage": {
            "requested_probe_count": result.requested_probe_count,
            "upstream_probe_count": result.upstream_probe_count,
            "cache_hit_count": result.cache_hit_count,
            "billable_probe_count": result.upstream_probe_count,
            "primary_upstream_probe_count": result.primary_upstream_probe_count,
            "primary_cache_hit_count": result.primary_cache_hit_count,
            "strict_verification_upstream_probe_count": (
                result.strict_verification_upstream_probe_count
            ),
            "strict_verification_cache_hit_count": (
                result.strict_verification_cache_hit_count
            ),
        },
        "verification": {
            "auto_strict_events": result.verification_events,
            "strict_attempted": any(
                item.get("attempted") for item in result.verification_events
            ),
            "strict_succeeded": any(
                item.get("succeeded") for item in result.verification_events
            ),
        },
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
