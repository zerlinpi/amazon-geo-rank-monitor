from fastapi import APIRouter, Depends, HTTPException, Request

from amazon_geo_rank_monitor.api.dependencies import current_tenant, get_services
from amazon_geo_rank_monitor.api.schemas import RankCheckBody
from amazon_geo_rank_monitor.application.rank_application import (
    execute_rank_check,
    serialize_execution_result,
)

router = APIRouter(prefix="/api/v1", tags=["rank"])


@router.post("/rank/check")
async def check_rank(
    body: RankCheckBody,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    services = get_services(request)
    try:
        result = await execute_rank_check(
            services=services,
            owner_id=owner_id,
            marketplace=body.marketplace,
            keyword=body.keyword,
            asins=body.asins,
            geo_profile_ids=body.geo_profile_ids,
            search_depth=body.search_depth,
            provider_mode=body.provider_mode,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return serialize_execution_result(result)


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
