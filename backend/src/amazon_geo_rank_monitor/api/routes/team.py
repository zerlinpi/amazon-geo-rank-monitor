from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from amazon_geo_rank_monitor.api.dependencies import (
    Principal,
    get_services,
    require_scope,
    require_scope_principal,
)
from amazon_geo_rank_monitor.api.schemas import (
    BootstrapOwnerCreate,
    InvitationCreate,
    MemberRoleUpdate,
)
from amazon_geo_rank_monitor.api.session_cookies import session_payload, set_session_cookies
from amazon_geo_rank_monitor.auth.accounts import ROLES, HumanPrincipal
from amazon_geo_rank_monitor.auth.api_keys import ApiPrincipal

router = APIRouter(prefix="/api/v1/team", tags=["team"])

TeamReadOwner = Annotated[str, Depends(require_scope("team:read"))]
TeamManageOwner = Annotated[str, Depends(require_scope("team:manage"))]
TeamManagePrincipal = Annotated[
    Principal,
    Depends(require_scope_principal("team:manage")),
]


@router.get("/members")
def list_members(
    request: Request,
    owner_id: TeamReadOwner,
):
    return get_services(request).account_repository.list_members(owner_id=owner_id)


@router.get("/invitations")
def list_invitations(
    request: Request,
    owner_id: TeamManageOwner,
):
    return get_services(request).account_repository.list_invitations(owner_id=owner_id)


@router.post("/invitations", status_code=status.HTTP_201_CREATED)
def create_invitation(
    body: InvitationCreate,
    request: Request,
    principal: TeamManagePrincipal,
):
    if not isinstance(principal, HumanPrincipal):
        raise HTTPException(
            status_code=403,
            detail="human session required to create invitations",
        )
    services = get_services(request)
    try:
        invitation = services.accounts.create_invitation(
            principal=principal,
            email=body.email,
            role=body.role,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "invitation_token": invitation.plaintext,
        "expires_at": invitation.expires_at,
    }


@router.patch("/members/{user_id}")
def update_member_role(
    user_id: str,
    body: MemberRoleUpdate,
    request: Request,
    principal: TeamManagePrincipal,
):
    if not isinstance(principal, HumanPrincipal):
        raise HTTPException(
            status_code=403,
            detail="human session required to update team members",
        )
    if body.role not in ROLES:
        raise HTTPException(status_code=422, detail="unsupported workspace role")
    services = get_services(request)
    try:
        target = services.account_repository.get_membership(
            user_id=user_id,
            owner_id=principal.owner_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workspace membership not found") from exc

    if isinstance(principal, HumanPrincipal) and principal.role == "admin":
        if target["role"] in {"owner", "admin"} or body.role in {"owner", "admin"}:
            raise HTTPException(
                status_code=403,
                detail="admins can only manage analyst and viewer roles",
            )
    try:
        return services.account_repository.update_member_role(
            owner_id=principal.owner_id,
            user_id=user_id,
            role=body.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: str,
    request: Request,
    principal: TeamManagePrincipal,
):
    if not isinstance(principal, HumanPrincipal):
        raise HTTPException(
            status_code=403,
            detail="human session required to remove team members",
        )
    services = get_services(request)
    try:
        target = services.account_repository.get_membership(
            user_id=user_id,
            owner_id=principal.owner_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workspace membership not found") from exc

    if isinstance(principal, HumanPrincipal) and principal.role == "admin":
        if target["role"] in {"owner", "admin"}:
            raise HTTPException(
                status_code=403,
                detail="admins cannot remove owners or admins",
            )
    try:
        services.account_repository.remove_member(
            owner_id=principal.owner_id,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/bootstrap-owner", status_code=status.HTTP_201_CREATED)
def bootstrap_owner(
    body: BootstrapOwnerCreate,
    request: Request,
    response: Response,
    principal: TeamManagePrincipal,
):
    if not isinstance(principal, ApiPrincipal):
        raise HTTPException(
            status_code=403,
            detail="API key authentication required for owner bootstrap",
        )
    services = get_services(request)
    try:
        created = services.accounts.bootstrap_owner(
            owner_id=principal.owner_id,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    set_session_cookies(response, services, created)
    return session_payload(services, created)
