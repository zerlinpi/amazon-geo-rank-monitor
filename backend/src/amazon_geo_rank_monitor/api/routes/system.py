from fastapi import APIRouter, Depends, HTTPException, Request

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/workers")
def list_workers(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
):
    del owner_id
    repository = get_services(request).worker_status_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="worker status is unavailable")
    return repository.list()
