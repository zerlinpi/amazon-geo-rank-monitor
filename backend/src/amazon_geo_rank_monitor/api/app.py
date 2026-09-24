from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import (
    api_keys_router,
    billing_router,
    geo_profiles_router,
    monitors_router,
    rank_router,
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


def create_app(
    services: AppServices,
    *,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    app = FastAPI(title="Amazon Geo Rank Monitor", version="0.1.0")
    app.state.services = services
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

    app.include_router(geo_profiles_router)
    app.include_router(monitors_router)
    app.include_router(rank_router)
    app.include_router(api_keys_router)
    app.include_router(billing_router)
    return app
