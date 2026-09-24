from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def error_code(status_code: int, detail: object) -> str:
    message = str(detail).lower()
    if status_code == 401 and "required" in message:
        return "AUTH_REQUIRED"
    if status_code == 401:
        return "INVALID_API_KEY"
    if status_code == 403:
        return "FORBIDDEN"
    if status_code == 404:
        return "RESOURCE_NOT_FOUND"
    if status_code == 409:
        return "CONFLICT"
    if status_code == 422:
        return "VALIDATION_ERROR"
    if status_code == 429:
        return "RATE_LIMITED"
    return f"HTTP_{status_code}"


def error_payload(
    request: Request,
    *,
    status_code: int,
    detail: object,
    code: str | None = None,
) -> dict:
    message = detail if isinstance(detail, str) else str(detail)
    request_id = getattr(request.state, "request_id", None)
    return {
        "detail": detail,
        "error": {
            "code": code or error_code(status_code, detail),
            "message": message,
            "request_id": request_id,
        },
    }


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(
            request,
            status_code=exc.status_code,
            detail=exc.detail,
        ),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_payload(
            request,
            status_code=422,
            detail=exc.errors(),
            code="VALIDATION_ERROR",
        ),
    )
