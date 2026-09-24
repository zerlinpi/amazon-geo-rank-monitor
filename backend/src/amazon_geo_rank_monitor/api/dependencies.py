from __future__ import annotations

from typing import Annotated, Any

from fastapi import Header, HTTPException, Request, status


def get_services(request: Request) -> Any:
    return request.app.state.services


def current_tenant(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )
    owner_id = get_services(request).api_keys.authenticate(x_api_key)
    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API key",
        )
    return owner_id
