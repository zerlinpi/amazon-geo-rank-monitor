from fastapi import APIRouter, Depends, HTTPException, Request, status

from amazon_geo_rank_monitor.api.dependencies import current_tenant, get_services
from amazon_geo_rank_monitor.api.schemas import MonitorCreate
from amazon_geo_rank_monitor.domain.models import RankCheckRequest

router = APIRouter(prefix="/api/v1/monitors", tags=["monitors"])


def _request_for_monitor(services, monitor: dict, owner_id: str) -> RankCheckRequest:
    profiles = []
    for profile_id in monitor["geo_profile_ids"]:
        profile = services.geo_repository.get_domain(profile_id, owner_id=owner_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="geo profile not found")
        profiles.append(profile)
    return RankCheckRequest(
        marketplace=monitor["marketplace"],
        keyword=monitor["keyword"],
        asins=monitor["asins"],
        geo_profiles=profiles,
        search_depth=monitor["search_depth"],
    )


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
    rank_request = _request_for_monitor(services, monitor, owner_id)
    return services.job_repository.enqueue(
        owner_id=owner_id,
        monitor_target_id=monitor_id,
        provider_mode=monitor["provider_mode"],
        request_payload=rank_request.model_dump(mode="json"),
    )
