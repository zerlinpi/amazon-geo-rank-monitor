from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .errors import (
    error_payload,
    http_exception_handler,
    validation_exception_handler,
)
from .rate_limit import build_rate_limiter, rate_limit_identity
from .routes import (
    api_keys_router,
    auth_router,
    billing_router,
    geo_profiles_router,
    monitors_router,
    rank_router,
    system_router,
    team_router,
)


@dataclass
class AppServices:
    tenant_repository: Any
    geo_repository: Any
    monitor_repository: Any
    job_repository: Any
    rank_repository: Any
    api_keys: Any
    provider_registry: Any
    billing_repository: Any | None = None
    rate_card: Any | None = None
    stripe_billing: Any | None = None
    database_engine: Any | None = None
    worker_status_repository: Any | None = None
    audit_repository: Any | None = None
    rate_limiter: Any | None = None
    auth_rate_limiter: Any | None = None
    account_repository: Any | None = None
    accounts: Any | None = None
    allow_public_signup: bool = True
    session_cookie_name: str = "agrm_session"
    csrf_cookie_name: str = "agrm_csrf"
    trusted_device_cookie_name: str = "agrm_trusted_device"
    trusted_device_days: int = 30
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"


def create_app(
    services: AppServices,
    *,
    cors_origins: list[str] | None = None,
    api_rate_limit_per_minute: int = 120,
    auth_rate_limit_per_minute: int = 20,
) -> FastAPI:
    app = FastAPI(title="Amazon Geo Rank Monitor", version="0.1.0")
    app.state.services = services
    app.state.rate_limiter = services.rate_limiter or build_rate_limiter(
        requests_per_minute=api_rate_limit_per_minute,
    )
    app.state.auth_rate_limiter = services.auth_rate_limiter or build_rate_limiter(
        requests_per_minute=auth_rate_limit_per_minute,
        namespace="agrm:auth",
    )
    logger = logging.getLogger("amazon_geo_rank_monitor.api")
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.middleware("http")
    async def request_boundary(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID")
        if not request_id or len(request_id) > 128:
            request_id = uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()

        limiter = request.app.state.rate_limiter
        api_key = request.headers.get("X-API-Key")
        authorization = request.headers.get("Authorization")
        bearer_token = None
        if authorization:
            scheme, _, credential = authorization.partition(" ")
            if scheme.lower() == "bearer" and credential:
                bearer_token = credential
        session_cookie = request.cookies.get(services.session_cookie_name)
        rate_credential = api_key or bearer_token or session_cookie
        public_auth = request.url.path in {
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/auth/forgot-password",
            "/api/v1/auth/reset-password",
            "/api/v1/auth/verify-email",
            "/api/v1/auth/mfa/complete",
        }
        if public_auth and request.method == "POST":
            auth_limiter = request.app.state.auth_rate_limiter
            if auth_limiter.limit:
                client_ip = request.client.host if request.client else "unknown"
                allowed, _, retry_after = auth_limiter.check(
                    rate_limit_identity(f"ip:{client_ip}")
                )
                if not allowed:
                    response = JSONResponse(
                        status_code=429,
                        content=error_payload(
                            request,
                            status_code=429,
                            detail="authentication rate limit exceeded",
                            code="RATE_LIMITED",
                        ),
                        headers={"Retry-After": str(retry_after)},
                    )
                    response.headers["X-Request-ID"] = request_id
                    return response

        exempt = request.method == "OPTIONS" or request.url.path in {
            "/health",
            "/ready",
            "/api/v1/billing/webhook",
        }
        if rate_credential and not exempt and limiter.limit:
            allowed, remaining, retry_after = limiter.check(
                rate_limit_identity(rate_credential)
            )
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content=error_payload(
                        request,
                        status_code=429,
                        detail="API rate limit exceeded",
                        code="RATE_LIMITED",
                    ),
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limiter.limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )
                response.headers["X-Request-ID"] = request_id
                return response
        else:
            remaining = limiter.limit

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if rate_credential and not exempt and limiter.limit:
            response.headers["X-RateLimit-Limit"] = str(limiter.limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)

        principal = getattr(request.state, "api_principal", None)
        if (
            principal is not None
            and services.audit_repository is not None
            and request.url.path.startswith("/api/v1/")
        ):
            try:
                services.audit_repository.record(
                    owner_id=principal.owner_id,
                    api_key_id=getattr(principal, "key_id", None),
                    user_id=getattr(principal, "user_id", None),
                    actor_type=getattr(principal, "auth_type", "api_key"),
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    client_ip=request.client.host if request.client else None,
                    user_agent=request.headers.get("User-Agent"),
                )
            except Exception:
                logger.exception(
                    "audit_record_failed request_id=%s",
                    request_id,
                )

        logger.info(
            "api_request method=%s path=%s status=%s request_id=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
            (perf_counter() - started) * 1000,
        )
        return response
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        engine = services.database_engine
        if engine is None:
            return {"status": "ok"}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "database": "unavailable"},
            )
        return {"status": "ok", "database": "ok"}

    app.include_router(auth_router)
    app.include_router(team_router)
    app.include_router(geo_profiles_router)
    app.include_router(monitors_router)
    app.include_router(rank_router)
    app.include_router(api_keys_router)
    app.include_router(billing_router)
    app.include_router(system_router)
    return app
