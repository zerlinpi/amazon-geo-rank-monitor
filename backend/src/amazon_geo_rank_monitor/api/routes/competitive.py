from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope

router = APIRouter(prefix="/api/v1/competitive", tags=["competitive"])


@router.get("/monitors/{monitor_id}/summary")
def monitor_competitive_summary(
    monitor_id: str,
    request: Request,
    hours: int = Query(default=168, ge=1, le=8760),
    top_n: int = Query(default=20, ge=1, le=100),
    limit: int = Query(default=50, ge=1, le=200),
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
    hours: int = Query(default=168, ge=1, le=8760),
    top_n: int = Query(default=20, ge=1, le=100),
    asins: list[str] | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
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
