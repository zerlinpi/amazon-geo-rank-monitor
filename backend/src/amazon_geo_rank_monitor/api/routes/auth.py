from fastapi import APIRouter, HTTPException, Request, Response, status

from amazon_geo_rank_monitor.api.dependencies import (
    HumanPrincipalDependency,
    get_services,
)
from amazon_geo_rank_monitor.api.schemas import (
    AccountLogin,
    AccountRegister,
    InvitationAccept,
    PasswordChange,
    WorkspaceSwitch,
)
from amazon_geo_rank_monitor.api.session_cookies import (
    clear_session_cookies,
    session_payload,
    set_session_cookies,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _client_context(request: Request) -> dict[str, str | None]:
    return {
        "client_ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("User-Agent"),
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: AccountRegister, request: Request, response: Response):
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
            **_client_context(request),
        )
    except ValueError as exc:
        message = str(exc)
        code = 409 if "already exists" in message else 422
        raise HTTPException(status_code=code, detail=message) from exc
    set_session_cookies(response, services, created)
    return session_payload(services, created)


@router.post("/login")
def login(body: AccountLogin, request: Request, response: Response):
    services = get_services(request)
    if services.accounts is None:
        raise HTTPException(status_code=503, detail="account authentication is unavailable")
    try:
        created = services.accounts.login(
            email=body.email,
            password=body.password,
            workspace_id=body.workspace_id,
            **_client_context(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    set_session_cookies(response, services, created)
    return session_payload(services, created)


@router.get("/me")
def me(
    request: Request,
    principal: HumanPrincipalDependency,
):
    return get_services(request).accounts.profile(principal)


@router.get("/sessions")
def sessions(
    request: Request,
    principal: HumanPrincipalDependency,
):
    return get_services(request).accounts.list_sessions(principal)


@router.post("/change-password")
def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    principal: HumanPrincipalDependency,
):
    services = get_services(request)
    try:
        revoked = services.accounts.change_password(
            principal=principal,
            current_password=body.current_password,
            new_password=body.new_password,
        )
        rotated = services.accounts.rotate_session(
            principal=principal,
            **_client_context(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    set_session_cookies(response, services, rotated)
    return {
        "revoked_other_sessions": revoked,
        "expires_at": rotated.expires_at,
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(
    session_id: str,
    request: Request,
    response: Response,
    principal: HumanPrincipalDependency,
):
    services = get_services(request)
    revoked = services.accounts.revoke_user_session(
        principal=principal,
        session_id=session_id,
    )
    if not revoked:
        raise HTTPException(status_code=404, detail="session not found")
    if session_id == principal.session_id:
        clear_session_cookies(response, services)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    request: Request,
    response: Response,
    principal: HumanPrincipalDependency,
):
    services = get_services(request)
    services.accounts.logout_all(principal)
    clear_session_cookies(response, services)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    principal: HumanPrincipalDependency,
):
    services = get_services(request)
    services.accounts.logout(principal.session_id)
    clear_session_cookies(response, services)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/switch-workspace")
def switch_workspace(
    body: WorkspaceSwitch,
    request: Request,
    response: Response,
    principal: HumanPrincipalDependency,
):
    services = get_services(request)
    try:
        created = services.accounts.switch_workspace(
            principal=principal,
            owner_id=body.workspace_id,
            **_client_context(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workspace membership not found") from exc
    set_session_cookies(response, services, created)
    return session_payload(services, created)


@router.post("/accept-invitation")
def accept_invitation(
    body: InvitationAccept,
    request: Request,
    response: Response,
    principal: HumanPrincipalDependency,
):
    services = get_services(request)
    try:
        created = services.accounts.accept_invitation(
            principal=principal,
            invitation_token=body.invitation_token,
            **_client_context(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    set_session_cookies(response, services, created)
    return session_payload(services, created)
