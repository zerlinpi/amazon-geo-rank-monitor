from fastapi import APIRouter, Depends, HTTPException, Request, status

from amazon_geo_rank_monitor.api.dependencies import current_tenant, get_services
from amazon_geo_rank_monitor.domain.models import GeoProfile

router = APIRouter(prefix="/api/v1/geo-profiles", tags=["geo-profiles"])


@router.get("")
def list_geo_profiles(
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    return get_services(request).geo_repository.list(owner_id=owner_id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_geo_profile(
    profile: GeoProfile,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    if profile.marketplace.strip() == "":
        raise HTTPException(status_code=422, detail="marketplace required")
    return get_services(request).geo_repository.create(
        owner_id=owner_id,
        profile=profile,
    )
