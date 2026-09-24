from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


class VerificationLevel(StrEnum):
    MANAGED = "managed"
    STRICT = "strict"


class ProbeStatus(StrEnum):
    SUCCESS_FOUND = "success_found"
    SUCCESS_NOT_FOUND = "success_not_found"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_RATE_LIMITED = "upstream_rate_limited"
    UPSTREAM_BLOCKED = "upstream_blocked"
    PARSER_FAILED = "parser_failed"
    GEO_VERIFICATION_FAILED = "geo_verification_failed"


class GeoProfile(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    marketplace: str = Field(min_length=1)
    ip_country: str = Field(min_length=2)
    ip_state: str | None = None
    ip_city: str | None = None
    ip_postal_code: str | None = None
    delivery_country: str = Field(min_length=2)
    delivery_postal_code: str = Field(min_length=1)
    device: Literal["desktop", "mobile"] = "desktop"
    weight: Decimal = Field(gt=0)
    enabled: bool = True

    @field_validator(
        "id",
        "name",
        "marketplace",
        "ip_country",
        "delivery_country",
        "delivery_postal_code",
    )
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("ip_state", "ip_city", "ip_postal_code")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class RankCheckRequest(BaseModel):
    marketplace: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    asins: list[str] = Field(min_length=1)
    geo_profiles: list[GeoProfile] = Field(min_length=1)
    search_depth: int = Field(default=100, ge=1)

    @field_validator("marketplace", "keyword")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("asins")
    @classmethod
    def normalize_asins(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            asin = value.strip().upper()
            if not asin:
                raise ValueError("ASIN must not be blank")
            if asin not in seen:
                normalized.append(asin)
                seen.add(asin)
        if not normalized:
            raise ValueError("at least one ASIN is required")
        return normalized

    @model_validator(mode="after")
    def validate_geo_marketplace(self) -> RankCheckRequest:
        mismatched = [
            profile.id
            for profile in self.geo_profiles
            if profile.marketplace != self.marketplace
        ]
        if mismatched:
            raise ValueError(
                f"geo profiles use a different marketplace: {', '.join(mismatched)}"
            )
        return self


class SerpProduct(BaseModel):
    asin: str = Field(min_length=1)
    position: int = Field(ge=1)
    page: int = Field(default=1, ge=1)
    sponsored: bool = False
    title: str | None = None

    @field_validator("asin")
    @classmethod
    def normalize_asin(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("ASIN must not be blank")
        return value


class SerpResult(BaseModel):
    organic_products: list[SerpProduct] = Field(default_factory=list)
    sponsored_products: list[SerpProduct] = Field(default_factory=list)
    absolute_products: list[SerpProduct] = Field(default_factory=list)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    geo_metadata: dict[str, Any] = Field(default_factory=dict)
    raw_result_reference: str | None = None


class RankObservation(BaseModel):
    asin: str
    geo_profile_id: str
    provider: str
    verification_level: VerificationLevel
    status: ProbeStatus
    found: bool
    organic_rank: int | None = Field(default=None, ge=1)
    absolute_rank: int | None = Field(default=None, ge=1)
    sponsored_rank: int | None = Field(default=None, ge=1)
    effective_rank: int = Field(ge=1)
    page: int | None = Field(default=None, ge=1)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_result_reference: str | None = None

    @field_validator("asin")
    @classmethod
    def normalize_asin(cls, value: str) -> str:
        return value.strip().upper()


class RankSnapshot(BaseModel):
    asin: str
    weighted_rank: Decimal
    found_weight: Decimal
    missing_weight: Decimal
    confidence: Decimal = Decimal("1")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("asin")
    @classmethod
    def normalize_asin(cls, value: str) -> str:
        return value.strip().upper()


class RankExecutionResult(BaseModel):
    run_id: str
    status: str
    observations: list[RankObservation]
    snapshots: list[RankSnapshot]
    errors: list[str] = Field(default_factory=list)


class ProxyLocation(BaseModel):
    ip: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    postal_code: str | None = None

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None

    @field_validator("state", "city", "postal_code", "ip")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class GeoVerificationResult(BaseModel):
    requested_ip_country: str | None = None
    requested_ip_state: str | None = None
    requested_ip_city: str | None = None
    requested_ip_postal_code: str | None = None
    observed_ip: ProxyLocation
    requested_delivery_postal_code: str
    confirmed_delivery_postal_code: str | None = None

    @staticmethod
    def _matches(requested: str | None, observed: str | None) -> bool:
        if requested is None:
            return True
        if observed is None:
            return False
        return requested.strip().casefold() == observed.strip().casefold()

    @computed_field
    @property
    def ip_verified(self) -> bool:
        if not self._matches(self.requested_ip_country, self.observed_ip.country):
            return False
        if self.requested_ip_postal_code is not None:
            return self._matches(
                self.requested_ip_postal_code,
                self.observed_ip.postal_code,
            )
        return all(
            (
                self._matches(self.requested_ip_state, self.observed_ip.state),
                self._matches(self.requested_ip_city, self.observed_ip.city),
            )
        )

    @computed_field
    @property
    def delivery_verified(self) -> bool:
        return self._matches(
            self.requested_delivery_postal_code,
            self.confirmed_delivery_postal_code,
        )

    @computed_field
    @property
    def strict_verified(self) -> bool:
        return self.ip_verified and self.delivery_verified


class StrictProbeMetadata(BaseModel):
    session_id: str
    verification: GeoVerificationResult
