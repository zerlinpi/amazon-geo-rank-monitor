from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from amazon_geo_rank_monitor.api.dependencies import (
    HumanPrincipalDependency,
    get_services,
)
from amazon_geo_rank_monitor.api.schemas import (
    AccountLogin,
    AccountRegister,
    EmailVerificationRequest,
    ForgotPasswordRequest,
    InvitationAccept,
    MfaCodeRequest,
    MfaCompleteRequest,
    MfaDisableRequest,
    PasswordChange,
    PasswordResetRequest,
    SsoStartRequest,
    WorkspaceSwitch,
)
from amazon_geo_rank_monitor.api.session_cookies import (
    clear_session_cookies,
    clear_trusted_device_cookie,
    session_payload,
    set_session_cookies,
    set_trusted_device_cookie,
)
from amazon_geo_rank_monitor.auth.accounts import (
    AccountLockedError,
    MfaChallenge,
    SsoRequiredError,
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
            trusted_device_token=request.cookies.get(
                services.trusted_device_cookie_name
            ),
            **_client_context(request),
        )
    except AccountLockedError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except SsoRequiredError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if isinstance(created, MfaChallenge):
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            "mfa_required": True,
            "challenge_token": created.plaintext,
            "expires_at": created.expires_at,
        }
    set_session_cookies(response, services, created)
    return {
        "mfa_required": False,
        **session_payload(services, created),
    }


@router.post("/mfa/complete")
def complete_mfa(
    body: MfaCompleteRequest,
    request: Request,
    response: Response,
):
    services = get_services(request)
    try:
        created = services.accounts.complete_mfa_login(
            challenge_token=body.challenge_token,
            code=body.code,
            remember_device=body.remember_device,
            **_client_context(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    set_session_cookies(response, services, created)
    if created.trusted_device_token and created.trusted_device_expires_at:
        set_trusted_device_cookie(
            response,
            services,
            token=created.trusted_device_token,
            expires_at=created.trusted_device_expires_at,
        )
    return {
        "mfa_required": False,
        **session_payload(services, created),
    }


@router.post("/mfa/enroll")
def begin_mfa_enrollment(
    request: Request,
    principal: HumanPrincipalDependency,
):
    try:
        return get_services(request).accounts.begin_mfa_enrollment(
            principal=principal
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/mfa/enroll/verify")
def confirm_mfa_enrollment(
    body: MfaCodeRequest,
    request: Request,
    principal: HumanPrincipalDependency,
):
    try:
        recovery_codes = get_services(request).accounts.confirm_mfa_enrollment(
            principal=principal,
            code=body.code,
            **_client_context(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"enabled": True, "recovery_codes": recovery_codes}


@router.post("/mfa/session-verify")
def verify_session_mfa(
    body: MfaCodeRequest,
    request: Request,
    principal: HumanPrincipalDependency,
):
    try:
        get_services(request).accounts.verify_current_session_mfa(
            principal=principal,
            code=body.code,
            **_client_context(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"verified": True}


@router.post("/mfa/recovery-codes/regenerate")
def regenerate_recovery_codes(
    body: MfaCodeRequest,
    request: Request,
    principal: HumanPrincipalDependency,
):
    try:
        codes = get_services(request).accounts.regenerate_recovery_codes(
            principal=principal,
            code=body.code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"recovery_codes": codes}


@router.post("/mfa/disable")
def disable_mfa(
    body: MfaDisableRequest,
    request: Request,
    response: Response,
    principal: HumanPrincipalDependency,
):
    services = get_services(request)
    try:
        services.accounts.disable_mfa(
            principal=principal,
            password=body.current_password,
            code=body.code,
            **_client_context(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    clear_trusted_device_cookie(response, services)
    return {"enabled": False}


@router.get("/sso/discover")
def discover_sso(email: str, request: Request):
    services = get_services(request)
    if services.sso is None:
        return []
    try:
        return services.sso.discover(email=email)
    except ValueError:
        return []


@router.post("/sso/start")
def start_sso(body: SsoStartRequest, request: Request):
    services = get_services(request)
    if services.sso is None:
        raise HTTPException(status_code=503, detail="SSO is unavailable")
    try:
        started = services.sso.start_login(
            owner_id=body.workspace_id,
            email_hint=body.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "authorization_url": started.authorization_url,
        "expires_at": started.expires_at,
    }


@router.get("/sso/callback")
def sso_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
):
    services = get_services(request)
    if services.sso is None:
        return RedirectResponse(
            "http://localhost:5173/#/login?sso=failed",
            status_code=302,
        )
    if error or not state or not code:
        return RedirectResponse(
            services.sso.failure_redirect_url(),
            status_code=302,
        )
    try:
        completed = services.sso.complete_login(
            state=state,
            code=code,
            **_client_context(request),
        )
    except ValueError:
        return RedirectResponse(
            services.sso.failure_redirect_url(),
            status_code=302,
        )
    response = RedirectResponse(
        services.sso.success_redirect_url(),
        status_code=302,
    )
    set_session_cookies(response, services, completed.session)
    return response


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(body: ForgotPasswordRequest, request: Request):
    services = get_services(request)
    try:
        services.accounts.forgot_password(
            email=body.email,
            **_client_context(request),
        )
    except ValueError:
        pass
    return {
        "accepted": True,
        "message": "If the account exists, a password reset email will be sent.",
    }


@router.post("/reset-password")
def reset_password(
    body: PasswordResetRequest,
    request: Request,
    response: Response,
):
    services = get_services(request)
    try:
        revoked = services.accounts.reset_password(
            token=body.token,
            new_password=body.new_password,
            **_client_context(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    clear_session_cookies(response, services)
    clear_trusted_device_cookie(response, services)
    return {"reset": True, "revoked_sessions": revoked}


@router.post("/verify-email")
def verify_email(body: EmailVerificationRequest, request: Request):
    try:
        user = get_services(request).accounts.verify_email(
            token=body.token,
            **_client_context(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "verified": True,
        "email": user["email"],
        "email_verified_at": user["email_verified_at"],
    }


@router.post("/resend-verification")
def resend_verification(
    request: Request,
    principal: HumanPrincipalDependency,
):
    sent = get_services(request).accounts.resend_verification(
        principal=principal,
        **_client_context(request),
    )
    return {"sent": sent}


@router.get("/security-events")
def security_events(
    request: Request,
    principal: HumanPrincipalDependency,
    limit: int = 100,
):
    return get_services(request).accounts.list_auth_events(
        principal=principal,
        limit=limit,
    )


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
    clear_trusted_device_cookie(response, services)
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
    clear_trusted_device_cookie(response, services)
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
    except SsoRequiredError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
