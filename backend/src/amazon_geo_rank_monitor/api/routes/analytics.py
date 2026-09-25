from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/monitors/{monitor_id}/trend")
def monitor_trend(
    monitor_id: str,
    request: Request,
    hours: int = 168,
    asin: str | None = None,
    geo_profile_id: str | None = None,
    owner_id: str = Depends(require_scope("rank:read")),
):
    try:
        return get_services(request).analytics.trend(
            owner_id=owner_id,
            monitor_target_id=monitor_id,
            hours=hours,
            asin=asin,
            geo_profile_id=geo_profile_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="monitor not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/monitors/{monitor_id}/summary")
def monitor_summary(
    monitor_id: str,
    request: Request,
    hours: int = 168,
    owner_id: str = Depends(require_scope("rank:read")),
):
    try:
        return get_services(request).analytics.summary(
            owner_id=owner_id,
            monitor_target_id=monitor_id,
            hours=hours,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="monitor not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/monitors/{monitor_id}/export.csv")
def export_monitor_csv(
    monitor_id: str,
    request: Request,
    hours: int = 168,
    granularity: str = "aggregate",
    owner_id: str = Depends(require_scope("rank:read")),
):
    try:
        content, filename = get_services(request).analytics.export_csv(
            owner_id=owner_id,
            monitor_target_id=monitor_id,
            hours=hours,
            granularity=granularity,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="monitor not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
