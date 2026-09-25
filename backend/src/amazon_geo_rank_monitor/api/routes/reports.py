from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope
from amazon_geo_rank_monitor.api.schemas import (
    ReportScheduleCreate,
    ReportScheduleUpdate,
)

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("/schedules")
def list_report_schedules(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
):
    return get_services(request).reports.list_schedules(owner_id=owner_id)


@router.post("/schedules", status_code=status.HTTP_201_CREATED)
def create_report_schedule(
    body: ReportScheduleCreate,
    request: Request,
    owner_id: str = Depends(require_scope("system:write")),
):
    try:
        return get_services(request).reports.create_schedule(
            owner_id=owner_id,
            name=body.name,
            monitor_target_ids=body.monitor_target_ids,
            recipients=body.recipients,
            schedule=body.schedule,
            lookback_hours=body.lookback_hours,
            include_csv=body.include_csv,
            enabled=body.enabled,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/schedules/{schedule_id}")
def update_report_schedule(
    schedule_id: str,
    body: ReportScheduleUpdate,
    request: Request,
    owner_id: str = Depends(require_scope("system:write")),
):
    try:
        return get_services(request).reports.update_schedule(
            owner_id=owner_id,
            schedule_id=schedule_id,
            changes=body.model_dump(exclude_unset=True),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="report schedule not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_report_schedule(
    schedule_id: str,
    request: Request,
    owner_id: str = Depends(require_scope("system:write")),
):
    try:
        get_services(request).reports.delete_schedule(
            owner_id=owner_id,
            schedule_id=schedule_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="report schedule not found",
        ) from exc


@router.post("/schedules/{schedule_id}/send")
def send_report_now(
    schedule_id: str,
    request: Request,
    owner_id: str = Depends(require_scope("system:write")),
):
    try:
        delivery = get_services(request).reports.dispatch_schedule(
            owner_id=owner_id,
            schedule_id=schedule_id,
            scheduled_for=datetime.now(UTC),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="report schedule not found",
        ) from exc
    if delivery is None:
        raise HTTPException(
            status_code=409,
            detail="report delivery was already dispatched",
        )
    return delivery


@router.get("/deliveries")
def list_report_deliveries(
    request: Request,
    limit: int = 100,
    owner_id: str = Depends(require_scope("system:read")),
):
    return get_services(request).reports.list_deliveries(
        owner_id=owner_id,
        limit=limit,
    )
