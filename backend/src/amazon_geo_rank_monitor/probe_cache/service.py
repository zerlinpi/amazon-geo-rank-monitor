from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    SerpResult,
    VerificationLevel,
)


@dataclass(frozen=True)
class ProbeCacheHit:
    cache_key: str
    result: SerpResult
    fetched_at: datetime
    age_seconds: int


class ProbeCacheService:
    def __init__(
        self,
        *,
        repository,
        managed_ttl_seconds: int = 300,
        strict_ttl_seconds: int = 0,
        retention_hours: int = 24,
    ) -> None:
        if managed_ttl_seconds < 0 or strict_ttl_seconds < 0:
            raise ValueError("probe cache TTL values must be non-negative")
        if retention_hours < 1:
            raise ValueError("probe cache retention must be at least 1 hour")
        self._repository = repository
        self._ttls = {
            "managed": managed_ttl_seconds,
            "strict": strict_ttl_seconds,
        }
        self._retention = timedelta(hours=retention_hours)

    def ttl_seconds(self, provider_mode: str) -> int:
        return int(self._ttls.get(provider_mode, 0))

    def lookup(
        self,
        *,
        owner_id: str | None,
        provider_mode: str,
        provider,
        marketplace: str,
        keyword: str,
        geo_profile: GeoProfile,
        search_depth: int,
    ) -> ProbeCacheHit | None:
        ttl_seconds = self.ttl_seconds(provider_mode)
        if owner_id is None or ttl_seconds <= 0:
            return None
        cache_key, _ = self._identity(
            provider_mode=provider_mode,
            provider=provider,
            marketplace=marketplace,
            keyword=keyword,
            geo_profile=geo_profile,
            search_depth=search_depth,
        )
        now = datetime.now(UTC)
        row = self._repository.get_fresh(
            owner_id=owner_id,
            cache_key=cache_key,
            now=now,
        )
        if row is None:
            return None
        try:
            result = SerpResult.model_validate(row["result_payload"])
        except Exception:
            self._repository.delete_entry(
                owner_id=owner_id,
                cache_key=cache_key,
            )
            return None
        fetched_at = self._utc(row["fetched_at"])
        return ProbeCacheHit(
            cache_key=cache_key,
            result=result,
            fetched_at=fetched_at,
            age_seconds=max(int((now - fetched_at).total_seconds()), 0),
        )

    def store(
        self,
        *,
        owner_id: str | None,
        provider_mode: str,
        provider,
        marketplace: str,
        keyword: str,
        geo_profile: GeoProfile,
        search_depth: int,
        result: SerpResult,
    ) -> None:
        ttl_seconds = self.ttl_seconds(provider_mode)
        if owner_id is None or ttl_seconds <= 0:
            return
        cache_key, identity_payload = self._identity(
            provider_mode=provider_mode,
            provider=provider,
            marketplace=marketplace,
            keyword=keyword,
            geo_profile=geo_profile,
            search_depth=search_depth,
        )
        now = datetime.now(UTC)
        provider_name = str(
            getattr(provider, "provider_name", provider.__class__.__name__)
        )
        verification_level = getattr(
            provider,
            "verification_level",
            VerificationLevel.MANAGED,
        )
        verification_value = (
            verification_level.value
            if isinstance(verification_level, VerificationLevel)
            else str(verification_level)
        )
        self._repository.put(
            owner_id=owner_id,
            cache_key=cache_key,
            provider_mode=provider_mode,
            provider_name=provider_name,
            verification_level=verification_value,
            marketplace=marketplace,
            keyword=keyword,
            geo_profile_id=geo_profile.id,
            device=geo_profile.device,
            search_depth=search_depth,
            identity_payload=identity_payload,
            result_payload=result.model_dump(mode="json"),
            fetched_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self._repository.prune_expired(before=now - self._retention)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @staticmethod
    def _verification_value(provider) -> str:
        value = getattr(
            provider,
            "verification_level",
            VerificationLevel.MANAGED,
        )
        return value.value if isinstance(value, VerificationLevel) else str(value)

    def _identity(
        self,
        *,
        provider_mode: str,
        provider,
        marketplace: str,
        keyword: str,
        geo_profile: GeoProfile,
        search_depth: int,
    ) -> tuple[str, dict]:
        identity = {
            "provider_mode": provider_mode,
            "provider_name": str(
                getattr(provider, "provider_name", provider.__class__.__name__)
            ),
            "verification_level": self._verification_value(provider),
            "marketplace": marketplace,
            "keyword": keyword,
            "ip_country": geo_profile.ip_country,
            "ip_state": geo_profile.ip_state,
            "ip_city": geo_profile.ip_city,
            "ip_postal_code": geo_profile.ip_postal_code,
            "delivery_country": geo_profile.delivery_country,
            "delivery_postal_code": geo_profile.delivery_postal_code,
            "device": geo_profile.device,
            "search_depth": search_depth,
        }
        canonical = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode()).hexdigest(), identity
