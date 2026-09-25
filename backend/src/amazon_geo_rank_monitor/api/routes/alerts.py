from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope
from amazon_geo_rank_monitor.api.schemas import AlertRuleCreate, AlertRuleUpdate

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

AlertReadOwner = Annotated[str, Depends(require_scope("monitors:read"))]
AlertWriteOwner = Annotated[str, Depends(require_scope("monitors:write"))]


@router.get("/rules")
def list_rules(request: Request, owner_id: AlertReadOwner):
    services = get_services(request)
    if services.alerts is None:
        return []
    return services.alerts.list_rules(owner_id=owner_id)


@router.post("/rules", status_code=201)
def create_rule(
    body: AlertRuleCreate,
    request: Request,
    owner_id: AlertWriteOwner,
):
    services = get_services(request)
    if services.alerts is None:
        raise HTTPException(status_code=503, detail="alert service unavailable")
    try:
        return services.alerts.create_rule(
            owner_id=owner_id,
            monitor_target_id=body.monitor_target_id,
            name=body.name,
            rule_type=body.rule_type,
            threshold=body.threshold,
            asin=body.asin,
            geo_profile_id=body.geo_profile_id,
            channels=body.channels.model_dump(),
            cooldown_minutes=body.cooldown_minutes,
            enabled=body.enabled,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    body: AlertRuleUpdate,
    request: Request,
    owner_id: AlertWriteOwner,
):
    services = get_services(request)
    if services.alerts is None:
        raise HTTPException(status_code=503, detail="alert service unavailable")
    changes = body.model_dump(exclude_unset=True)
    if "channels" in changes and changes["channels"] is not None:
        changes["channels"] = body.channels.model_dump()
    try:
        return services.alerts.update_rule(
            owner_id=owner_id,
            rule_id=rule_id,
            changes=changes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: str,
    request: Request,
    owner_id: AlertWriteOwner,
):
    services = get_services(request)
    if services.alerts is None:
        raise HTTPException(status_code=503, detail="alert service unavailable")
    try:
        services.alerts.delete_rule(owner_id=owner_id, rule_id=rule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/events")
def list_events(
    request: Request,
    owner_id: AlertReadOwner,
    limit: int = Query(default=100, ge=1, le=500),
):
    services = get_services(request)
    if services.alerts is None:
        return []
    return services.alerts.list_events(owner_id=owner_id, limit=limit)
