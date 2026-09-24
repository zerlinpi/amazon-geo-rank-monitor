from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope
from amazon_geo_rank_monitor.api.schemas import ApiKeyCreate

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


def _public_key(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in {"key_hash", "owner_id"}
    }


@router.get("")
def list_api_keys(
    request: Request,
    owner_id: str = Depends(require_scope("keys:manage")),
):
    rows = get_services(request).tenant_repository.list_api_keys(owner_id=owner_id)
    return [_public_key(row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    created = get_services(request).api_keys.create(
        owner_id=owner_id,
        name=body.name,
        scopes=body.scopes,
    )
    return {
        "id": created.id,
        "prefix": created.prefix,
        "plaintext": created.plaintext,
        "scopes": list(created.scopes),
    }


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: str,
    request: Request,
    owner_id: str = Depends(current_tenant),
):
    try:
        get_services(request).api_keys.revoke(key_id, owner_id=owner_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="API key not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
