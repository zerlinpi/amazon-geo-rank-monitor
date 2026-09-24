from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from amazon_geo_rank_monitor.domain.errors import ConfigurationError
from amazon_geo_rank_monitor.domain.models import GeoProfile
from amazon_geo_rank_monitor.providers.oxylabs import OxylabsRankProvider
from amazon_geo_rank_monitor.providers.residential_proxy import (
    OxylabsResidentialProxyFactory,
)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+pysqlite:///./amazon_geo_rank_monitor.db"
    oxylabs_username: str | None = None
    oxylabs_password: str | None = None
    residential_proxy_username: str | None = None
    residential_proxy_password: str | None = None
    residential_proxy_server: str = "http://pr.oxylabs.io:7777"
    api_key_pepper: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_rate_limit_per_minute: int = 120
    redis_url: str | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    worker_poll_seconds: float = 2.0
    worker_id: str | None = None
    job_max_attempts: int = 3
    job_lease_seconds: float = 900.0
    job_retry_base_seconds: float = 30.0
    job_retry_max_seconds: float = 900.0
    scheduler_poll_seconds: float = 30.0
    scheduler_id: str | None = None
    auto_create_schema: bool = True
    mcp_tenant_id: str | None = None
    managed_serp_credit_cost: int = 1
    strict_serp_credit_cost: int = 5
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_success_url: str = "http://localhost:5173/billing/success"
    stripe_cancel_url: str = "http://localhost:5173/billing"
    billing_currency: str = "usd"
    credit_pack_starter_credits: int = 500
    credit_pack_starter_amount_minor: int = 0
    credit_pack_growth_credits: int = 2000
    credit_pack_growth_amount_minor: int = 0
    credit_pack_scale_credits: int = 10000
    credit_pack_scale_amount_minor: int = 0

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            item.strip()
            for item in self.cors_origins.split(",")
            if item.strip()
        ]


class GeoProfilesDocument(BaseModel):
    geo_profiles: list[GeoProfile]


def load_geo_profiles(path: str | Path) -> list[GeoProfile]:
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    document = GeoProfilesDocument.model_validate(payload or {})
    return document.geo_profiles


def build_oxylabs_provider(settings: AppSettings) -> OxylabsRankProvider:
    if not settings.oxylabs_username or not settings.oxylabs_password:
        raise ConfigurationError("OXYLABS_USERNAME and OXYLABS_PASSWORD are required")
    try:
        from oxylabs import RealtimeClient
    except ImportError as exc:
        raise ConfigurationError("Oxylabs SDK is not installed") from exc
    client = RealtimeClient(settings.oxylabs_username, settings.oxylabs_password)
    return OxylabsRankProvider(client=client)


def build_residential_proxy_factory(
    settings: AppSettings,
) -> OxylabsResidentialProxyFactory:
    if not settings.residential_proxy_username or not settings.residential_proxy_password:
        raise ConfigurationError(
            "RESIDENTIAL_PROXY_USERNAME and RESIDENTIAL_PROXY_PASSWORD are required"
        )
    return OxylabsResidentialProxyFactory(
        username=settings.residential_proxy_username,
        password=settings.residential_proxy_password,
        server=settings.residential_proxy_server,
    )
