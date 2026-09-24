from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from amazon_geo_rank_monitor.api.dependencies import current_tenant, get_services
from amazon_geo_rank_monitor.api.schemas import MonitorCreate
from amazon_geo_rank_monitor.application.rank_application import enqueue_monitor

router = APIRouter(prefix="/api/v1/monitors", tags=["monitors"])


@router.get("")
def list_monitors(
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    return get_services(request).monitor_repository.list(owner_id=owner_id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_monitor(
    body: MonitorCreate,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    services = get_services(request)
    try:
        return services.monitor_repository.create(
            owner_id=owner_id,
            name=body.name,
            marketplace=body.marketplace,
            keyword=body.keyword,
            asins=body.asins,
            geo_profile_ids=body.geo_profile_ids,
            search_depth=body.search_depth,
            provider_mode=body.provider_mode,
            schedule=body.schedule,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{monitor_id}")
def get_monitor(
    monitor_id: str,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    monitor = get_services(request).monitor_repository.get(
        monitor_id,
        owner_id=owner_id,
    )
    if monitor is None:
        raise HTTPException(status_code=404, detail="monitor not found")
    return monitor


@router.post("/{monitor_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_monitor(
    monitor_id: str,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    services = get_services(request)
    monitor = services.monitor_repository.get(monitor_id, owner_id=owner_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="monitor not found")
    return enqueue_monitor(
        services=services,
        owner_id=owner_id,
        monitor=monitor,
    )


@router.get("/{monitor_id}/history")
def get_monitor_history(
    monitor_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    owner_id: str = Depends(current_tenant),
):
    services = get_services(request)
    monitor = services.monitor_repository.get(monitor_id, owner_id=owner_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="monitor not found")

    jobs = services.job_repository.list(
        owner_id=owner_id,
        monitor_target_id=monitor_id,
        limit=limit,
    )
    history = []
    for job in jobs:
        run = None
        if job["run_id"]:
            try:
                run = services.rank_repository.get_run(
                    job["run_id"],
                    owner_id=owner_id,
                )
            except KeyError:
                run = None
        history.append({"job": job, "run": run})
    return history
