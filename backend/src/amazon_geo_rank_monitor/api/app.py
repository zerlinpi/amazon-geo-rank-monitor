from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from .routes import (
    api_keys_router,
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


def create_app(services: AppServices) -> FastAPI:
    app = FastAPI(title="Amazon Geo Rank Monitor", version="0.1.0")
    app.state.services = services

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(geo_profiles_router)
    app.include_router(monitors_router)
    app.include_router(rank_router)
    app.include_router(api_keys_router)
    return app
