from __future__ import annotations

from collections.abc import Callable
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

    if authorization:
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() == "bearer" and credential:
            accounts = getattr(services, "accounts", None)
            if accounts is not None:
                principal = accounts.authenticate_session(credential)

    if principal is None and x_api_key:
        client_ip = request.client.host if request.client else None
        principal = services.api_keys.authenticate_principal(
            x_api_key,
            client_ip=client_ip,
        )

    if principal is None:
        if not authorization and not x_api_key:
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
