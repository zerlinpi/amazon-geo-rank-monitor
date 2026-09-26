from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope

router = APIRouter(prefix="/api/v1/competitive", tags=["competitive"])


@router.get("/monitors/{monitor_id}/summary")
def monitor_competitive_summary(
    monitor_id: str,
    request: Request,
    hours: Annotated[int, Query(ge=1, le=8760)] = 168,
    top_n: Annotated[int, Query(ge=1, le=100)] = 20,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    include_tracked: bool = False,
    owner_id: str = Depends(require_scope("rank:read")),
):
    try:
        return get_services(request).competitive_intelligence.summary(
            owner_id=owner_id,
            monitor_target_id=monitor_id,
            hours=hours,
            top_n=top_n,
            limit=limit,
            include_tracked=include_tracked,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="monitor not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/monitors/{monitor_id}/trend")
def monitor_competitive_trend(
    monitor_id: str,
    request: Request,
    hours: Annotated[int, Query(ge=1, le=8760)] = 168,
    top_n: Annotated[int, Query(ge=1, le=100)] = 20,
    asins: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    owner_id: str = Depends(require_scope("rank:read")),
):
    try:
        return get_services(request).competitive_intelligence.trend(
            owner_id=owner_id,
            monitor_target_id=monitor_id,
            hours=hours,
            top_n=top_n,
            asins=asins,
            limit=limit,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="monitor not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
