from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from amazon_geo_rank_monitor.api.dependencies import get_services
from amazon_geo_rank_monitor.auth.scim import ScimPrincipal

router = APIRouter(prefix="/scim/v2", tags=["scim"])


def scim_json(
    payload: dict,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload),
        headers=headers,
        media_type="application/scim+json",
    )


def require_scim_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> ScimPrincipal:
    if not authorization:
        raise HTTPException(status_code=401, detail="SCIM bearer token required")
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise HTTPException(status_code=401, detail="SCIM bearer token required")
    services = get_services(request)
    if services.scim is None:
        raise HTTPException(status_code=503, detail="SCIM is unavailable")
    principal = services.scim.authenticate(credential)
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid SCIM bearer token")
    request.state.api_principal = principal
    return principal


ScimPrincipalDependency = Annotated[
    ScimPrincipal,
    Depends(require_scim_principal),
]


@router.get("/ServiceProviderConfig")
def service_provider_config(
    request: Request,
    principal: ScimPrincipalDependency,
):
    return scim_json(get_services(request).scim.service_provider_config())


@router.get("/ResourceTypes")
def resource_types(
    request: Request,
    principal: ScimPrincipalDependency,
):
    return scim_json(get_services(request).scim.resource_types())


@router.get("/Schemas")
def schemas(
    request: Request,
    principal: ScimPrincipalDependency,
):
    return scim_json(get_services(request).scim.schemas())


@router.get("/Users")
def list_users(
    request: Request,
    principal: ScimPrincipalDependency,
    filter_expression: str | None = Query(default=None, alias="filter"),
    start_index: int = Query(default=1, alias="startIndex", ge=1),
    count: int = Query(default=100, ge=0, le=200),
):
    try:
        payload = get_services(request).scim.list_users(
            owner_id=principal.owner_id,
            filter_expression=filter_expression,
            start_index=start_index,
            count=count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return scim_json(payload)


@router.post("/Users")
async def create_user(
    request: Request,
    principal: ScimPrincipalDependency,
):
    body = await request.json()
    try:
        payload = get_services(request).scim.create_user(
            owner_id=principal.owner_id,
            payload=body,
        )
    except ValueError as exc:
        status_code = 409 if "already exists" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return scim_json(
        payload,
        status_code=201,
        headers={"Location": f"/scim/v2/Users/{payload['id']}"},
    )


@router.get("/Users/{membership_id}")
def get_user(
    membership_id: str,
    request: Request,
    principal: ScimPrincipalDependency,
):
    try:
        payload = get_services(request).scim.get_user(
            owner_id=principal.owner_id,
            membership_id=membership_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SCIM user not found") from exc
    return scim_json(payload)


@router.put("/Users/{membership_id}")
async def replace_user(
    membership_id: str,
    request: Request,
    principal: ScimPrincipalDependency,
):
    body = await request.json()
    try:
        payload = get_services(request).scim.replace_user(
            owner_id=principal.owner_id,
            membership_id=membership_id,
            payload=body,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SCIM user not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return scim_json(payload)


@router.patch("/Users/{membership_id}")
async def patch_user(
    membership_id: str,
    request: Request,
    principal: ScimPrincipalDependency,
):
    body = await request.json()
    try:
        payload = get_services(request).scim.patch_user(
            owner_id=principal.owner_id,
            membership_id=membership_id,
            payload=body,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SCIM user not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return scim_json(payload)


@router.delete("/Users/{membership_id}", status_code=204)
def delete_user(
    membership_id: str,
    request: Request,
    principal: ScimPrincipalDependency,
):
    try:
        get_services(request).scim.delete_user(
            owner_id=principal.owner_id,
            membership_id=membership_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SCIM user not found") from exc
    return Response(status_code=204)


@router.get("/Groups")
def list_groups(
    request: Request,
    principal: ScimPrincipalDependency,
    filter_expression: str | None = Query(default=None, alias="filter"),
    start_index: int = Query(default=1, alias="startIndex", ge=1),
    count: int = Query(default=100, ge=0, le=200),
):
    try:
        payload = get_services(request).scim.list_groups(
            owner_id=principal.owner_id,
            filter_expression=filter_expression,
            start_index=start_index,
            count=count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return scim_json(payload)


@router.post("/Groups")
async def create_group(
    request: Request,
    principal: ScimPrincipalDependency,
):
    body = await request.json()
    try:
        payload = get_services(request).scim.create_group(
            owner_id=principal.owner_id,
            payload=body,
        )
    except ValueError as exc:
        status_code = 409 if "already exists" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return scim_json(
        payload,
        status_code=201,
        headers={"Location": f"/scim/v2/Groups/{payload['id']}"},
    )


@router.get("/Groups/{group_id}")
def get_group(
    group_id: str,
    request: Request,
    principal: ScimPrincipalDependency,
):
    try:
        payload = get_services(request).scim.get_group(
            owner_id=principal.owner_id,
            group_id=group_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SCIM group not found") from exc
    return scim_json(payload)


@router.put("/Groups/{group_id}")
async def replace_group(
    group_id: str,
    request: Request,
    principal: ScimPrincipalDependency,
):
    body = await request.json()
    try:
        payload = get_services(request).scim.replace_group(
            owner_id=principal.owner_id,
            group_id=group_id,
            payload=body,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SCIM group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return scim_json(payload)


@router.patch("/Groups/{group_id}")
async def patch_group(
    group_id: str,
    request: Request,
    principal: ScimPrincipalDependency,
):
    body = await request.json()
    try:
        payload = get_services(request).scim.patch_group(
            owner_id=principal.owner_id,
            group_id=group_id,
            payload=body,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SCIM group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return scim_json(payload)


@router.delete("/Groups/{group_id}", status_code=204)
def delete_group(
    group_id: str,
    request: Request,
    principal: ScimPrincipalDependency,
):
    try:
        get_services(request).scim.delete_group(
            owner_id=principal.owner_id,
            group_id=group_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SCIM group not found") from exc
    return Response(status_code=204)
