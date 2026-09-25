from __future__ import annotations

from collections.abc import Callable
import hmac
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status

from amazon_geo_rank_monitor.auth.accounts import HumanPrincipal
from amazon_geo_rank_monitor.auth.api_keys import ApiPrincipal

Principal = ApiPrincipal | HumanPrincipal


def get_services(request: Request) -> Any:
    return request.app.state.services


def current_principal(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Principal:
    cached = getattr(request.state, "api_principal", None)
    if cached is not None:
        return cached

    services = get_services(request)
    principal: Principal | None = None

    accounts = getattr(services, "accounts", None)
    client_ip = request.client.host if request.client else None

    if authorization:
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() == "bearer" and credential and accounts is not None:
            principal = accounts.authenticate_session(
                credential,
                client_ip=client_ip,
            )

    cookie_credential = request.cookies.get(
        getattr(services, "session_cookie_name", "agrm_session")
    )
    if principal is None and cookie_credential and accounts is not None:
        principal = accounts.authenticate_session(
            cookie_credential,
            client_ip=client_ip,
        )
        if principal is not None:
            request.state.auth_transport = "cookie"
            if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                csrf_cookie = request.cookies.get(
                    getattr(services, "csrf_cookie_name", "agrm_csrf")
                )
                csrf_header = request.headers.get("X-CSRF-Token")
                if (
                    not csrf_cookie
                    or not csrf_header
                    or not hmac.compare_digest(csrf_cookie, csrf_header)
                    or not accounts.verify_csrf(principal, csrf_header)
                ):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="valid CSRF token required",
                    )

    if principal is None and x_api_key:
        principal = services.api_keys.authenticate_principal(
            x_api_key,
            client_ip=client_ip,
        )

    if principal is None:
        if not authorization and not x_api_key and not cookie_credential:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication credentials",
        )

    request.state.api_principal = principal
    return principal


PrincipalDependency = Annotated[Principal, Depends(current_principal)]


def current_tenant(
    principal: PrincipalDependency,
) -> str:
    return principal.owner_id


def current_human_principal(
    principal: PrincipalDependency,
) -> HumanPrincipal:
    if not isinstance(principal, HumanPrincipal):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="human session required",
        )
    return principal


HumanPrincipalDependency = Annotated[
    HumanPrincipal,
    Depends(current_human_principal),
]


def require_scope(scope: str) -> Callable[..., str]:
    def dependency(
        principal: PrincipalDependency,
    ) -> str:
        if not principal.allows(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"scope required: {scope}",
            )
        return principal.owner_id

    return dependency


def require_scope_principal(scope: str) -> Callable[..., Principal]:
    def dependency(
        principal: PrincipalDependency,
    ) -> Principal:
        if not principal.allows(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"scope required: {scope}",
            )
        return principal

    return dependency
