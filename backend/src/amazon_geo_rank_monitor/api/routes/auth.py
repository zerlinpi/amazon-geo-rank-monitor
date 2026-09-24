from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from amazon_geo_rank_monitor.api.dependencies import (
    HumanPrincipalDependency,
    get_services,
)
from amazon_geo_rank_monitor.api.schemas import (
    AccountLogin,
    AccountRegister,
    InvitationAccept,
    WorkspaceSwitch,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _session_payload(services, session) -> dict:
    return {
        "session_token": session.plaintext,
        "expires_at": session.expires_at,
        **services.accounts.profile(session.principal),
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: AccountRegister, request: Request):
    services = get_services(request)
    if services.accounts is None:
        raise HTTPException(status_code=503, detail="account authentication is unavailable")
    if not services.allow_public_signup and not body.invitation_token:
        raise HTTPException(status_code=403, detail="public signup is disabled")
    try:
        created = services.accounts.register(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            workspace_name=body.workspace_name,
            invitation_token=body.invitation_token,
        )
    except ValueError as exc:
        message = str(exc)
        code = 409 if "already exists" in message else 422
        raise HTTPException(status_code=code, detail=message) from exc
    return _session_payload(services, created)


@router.post("/login")
def login(body: AccountLogin, request: Request):
    services = get_services(request)
    if services.accounts is None:
        raise HTTPException(status_code=503, detail="account authentication is unavailable")
    try:
        created = services.accounts.login(
            email=body.email,
            password=body.password,
            workspace_id=body.workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _session_payload(services, created)


@router.get("/me")
def me(
    request: Request,
    principal: HumanPrincipalDependency,
):
    return get_services(request).accounts.profile(principal)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    principal: HumanPrincipalDependency,
):
    get_services(request).accounts.logout(principal.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/switch-workspace")
def switch_workspace(
    body: WorkspaceSwitch,
    request: Request,
    principal: HumanPrincipalDependency,
):
    services = get_services(request)
    try:
        created = services.accounts.switch_workspace(
            principal=principal,
            owner_id=body.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workspace membership not found") from exc
    return _session_payload(services, created)


@router.post("/accept-invitation")
def accept_invitation(
    body: InvitationAccept,
    request: Request,
    principal: HumanPrincipalDependency,
):
    services = get_services(request)
    try:
        created = services.accounts.accept_invitation(
            principal=principal,
            invitation_token=body.invitation_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _session_payload(services, created)
