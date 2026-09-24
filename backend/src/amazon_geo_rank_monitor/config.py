from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from amazon_geo_rank_monitor.domain.errors import ConfigurationError
from amazon_geo_rank_monitor.domain.models import GeoProfile
from amazon_geo_rank_monitor.providers.oxylabs import OxylabsRankProvider


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./amazon_geo_rank_monitor.db"
    oxylabs_username: str | None = None
    oxylabs_password: str | None = None


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
