from fastapi import APIRouter, Depends, HTTPException, Request

from amazon_geo_rank_monitor.api.dependencies import current_tenant, get_services
from amazon_geo_rank_monitor.api.schemas import RankCheckBody
from amazon_geo_rank_monitor.domain.models import RankCheckRequest
from amazon_geo_rank_monitor.monitor.service import RankMonitorService

router = APIRouter(prefix="/api/v1", tags=["rank"])


def _serialize_result(result) -> dict:
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


@router.post("/rank/check")
async def check_rank(
    body: RankCheckBody,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    services = get_services(request)
    profiles = []
    for profile_id in body.geo_profile_ids:
        profile = services.geo_repository.get_domain(profile_id, owner_id=owner_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="geo profile not found")
        profiles.append(profile)
    rank_request = RankCheckRequest(
        marketplace=body.marketplace,
        keyword=body.keyword,
        asins=body.asins,
        geo_profiles=profiles,
        search_depth=body.search_depth,
    )
    try:
        provider = services.provider_registry.get(body.provider_mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    service = RankMonitorService(
        provider=provider,
        repository=services.rank_repository,
    )
    result = await service.check_with_result(rank_request, owner_id=owner_id)
    return _serialize_result(result)


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    try:
        return get_services(request).job_repository.get(job_id, owner_id=owner_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    try:
        return get_services(request).rank_repository.get_run(
            run_id,
            owner_id=owner_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
