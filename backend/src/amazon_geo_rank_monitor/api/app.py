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
from .rate_limit import FixedWindowRateLimiter
from .routes import (
    api_keys_router,
    billing_router,
    geo_profiles_router,
    monitors_router,
    rank_router,
    system_router,
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


def create_app(
    services: AppServices,
    *,
    cors_origins: list[str] | None = None,
    api_rate_limit_per_minute: int = 120,
) -> FastAPI:
    app = FastAPI(title="Amazon Geo Rank Monitor", version="0.1.0")
    app.state.services = services
    app.state.rate_limiter = FixedWindowRateLimiter(
        requests_per_minute=api_rate_limit_per_minute,
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
        exempt = request.method == "OPTIONS" or request.url.path in {
            "/health",
            "/ready",
            "/api/v1/billing/webhook",
        }
        if api_key and not exempt and limiter.limit:
            allowed, remaining, retry_after = limiter.check(api_key)
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
        if api_key and not exempt and limiter.limit:
            response.headers["X-RateLimit-Limit"] = str(limiter.limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)

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
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse | dict[str, str]:
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

    app.include_router(geo_profiles_router)
    app.include_router(monitors_router)
    app.include_router(rank_router)
    app.include_router(api_keys_router)
    app.include_router(billing_router)
    app.include_router(system_router)
    return app
