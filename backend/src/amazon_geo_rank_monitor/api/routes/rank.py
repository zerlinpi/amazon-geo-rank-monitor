from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime, BeforeValidator

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope
from amazon_geo_rank_monitor.api.schemas import RankCheckBody
from amazon_geo_rank_monitor.application.rank_application import (
    execute_rank_check,
    serialize_execution_result,
)

router = APIRouter(prefix="/api/v1", tags=["rank"])

# Parse ISO text before Pydantic can coerce numeric strings to Unix timestamps.
IsoAwareDatetime = Annotated[AwareDatetime, BeforeValidator(datetime.fromisoformat)]


@router.post("/rank/check")
async def check_rank(
    body: RankCheckBody,
    request: Request,
    owner_id: str = Depends(require_scope("rank:write")),
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
            force_strict_verification=body.force_strict_verification,
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
    owner_id: str = Depends(require_scope("rank:read")),
):
    try:
        return get_services(request).job_repository.get(job_id, owner_id=owner_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.get("/runs")
def list_runs(
    request: Request,
    owner_id: str = Depends(require_scope("rank:read")),
    limit: int = 50,
):
    return get_services(request).rank_repository.list_runs(
        owner_id=owner_id,
        limit=min(max(limit, 1), 500),
    )


@router.get("/runs/page")
def list_run_page(
    request: Request,
    owner_id: str = Depends(require_scope("rank:read")),
    limit: int = Query(50, ge=1, le=100),
    cursor: UUID | None = None,
    keyword: str | None = Query(None, max_length=512),
    asin: str | None = Query(None, max_length=32),
    status: Literal["running", "succeeded", "partially_succeeded", "failed"] | None = None,
    started_from: IsoAwareDatetime | None = None,
    started_until: IsoAwareDatetime | None = None,
):
    try:
        return get_services(request).rank_repository.list_run_page(
            owner_id=owner_id,
            limit=limit,
            cursor=str(cursor) if cursor else None,
            keyword=keyword,
            asin=asin,
            status=status,
            started_from=started_from,
            started_until=started_until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    request: Request,
    owner_id: str = Depends(require_scope("rank:read")),
):
    try:
        return get_services(request).rank_repository.get_run(
            run_id,
            owner_id=owner_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
