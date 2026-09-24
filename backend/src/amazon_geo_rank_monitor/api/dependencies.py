from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status

from amazon_geo_rank_monitor.auth.api_keys import ApiPrincipal


def get_services(request: Request) -> Any:
    return request.app.state.services


def current_principal(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> ApiPrincipal:
    cached = getattr(request.state, "api_principal", None)
    if cached is not None:
        return cached
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )
    principal = get_services(request).api_keys.authenticate_principal(x_api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API key",
        )
    request.state.api_principal = principal
    return principal


def current_tenant(
    principal: ApiPrincipal = Depends(current_principal),
) -> str:
    return principal.owner_id


def require_scope(scope: str) -> Callable[..., str]:
    def dependency(
        principal: ApiPrincipal = Depends(current_principal),
    ) -> str:
        if not principal.allows(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key scope required: {scope}",
            )
        return principal.owner_id

    return dependency
