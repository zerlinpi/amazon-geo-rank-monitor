from __future__ import annotations

import json
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.billing.stripe_gateway import StripeGateway
from amazon_geo_rank_monitor.billing.stripe_service import StripeBillingService
from amazon_geo_rank_monitor.billing.usage import RankUsageMeter
from amazon_geo_rank_monitor.config import (
    AppSettings,
    build_oxylabs_provider,
    build_residential_proxy_factory,
)
from amazon_geo_rank_monitor.domain.errors import ConfigurationError
from amazon_geo_rank_monitor.domain.models import VerificationLevel
from amazon_geo_rank_monitor.providers.playwright_amazon import (
    PlaywrightAmazonBrowserClient,
)
from amazon_geo_rank_monitor.providers.strict_browser import StrictBrowserRankProvider
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository


class UnavailableProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        verification_level: VerificationLevel,
        reason: str,
    ) -> None:
        self.provider_name = provider_name
        self.verification_level = verification_level
        self._reason = reason

    async def search(self, **_: Any):
        raise ConfigurationError(self._reason)


def _engine(settings: AppSettings):
    if settings.database_url in {
        "sqlite+pysqlite:///:memory:",
        "sqlite:///:memory:",
        "sqlite+pysqlite://",
    }:
        return create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(settings.database_url)


def _managed_provider(settings: AppSettings):
    if settings.oxylabs_username and settings.oxylabs_password:
        return build_oxylabs_provider(settings)
    return UnavailableProvider(
        provider_name="oxylabs",
        verification_level=VerificationLevel.MANAGED,
        reason="Oxylabs managed provider credentials are not configured",
    )


def _strict_provider(settings: AppSettings):
    if settings.residential_proxy_username and settings.residential_proxy_password:
        proxy_factory = build_residential_proxy_factory(settings)
        return StrictBrowserRankProvider(
            proxy_factory=proxy_factory,
            browser_client_factory=lambda proxy: PlaywrightAmazonBrowserClient(proxy),
        )
    return UnavailableProvider(
        provider_name="strict_browser",
        verification_level=VerificationLevel.STRICT,
        reason="Residential proxy credentials are not configured",
    )


def _seed_credit_packs(
    *,
    billing_repository: BillingRepository,
    serialized: str | None,
) -> None:
    if not serialized:
        return
    try:
        packs = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("CREDIT_PACKS_JSON must be valid JSON") from exc
    if not isinstance(packs, list):
        raise ConfigurationError("CREDIT_PACKS_JSON must contain a JSON array")

    for pack in packs:
        if not isinstance(pack, dict):
            raise ConfigurationError("each credit pack must be a JSON object")
        required = {"id", "name", "credits", "stripe_price_id"}
        if not required.issubset(pack):
            raise ConfigurationError(
                "credit pack requires id, name, credits, and stripe_price_id"
            )
        billing_repository.create_credit_pack(
            pack_id=str(pack["id"]),
            name=str(pack["name"]),
            credits=int(pack["credits"]),
            stripe_price_id=str(pack["stripe_price_id"]),
            active=bool(pack.get("active", True)),
            display_order=int(pack.get("display_order", 0)),
        )


def _stripe_billing(
    *,
    settings: AppSettings,
    repository: BillingRepository,
) -> StripeBillingService | None:
    required = (
        settings.stripe_secret_key,
        settings.stripe_webhook_secret,
        settings.stripe_success_url,
        settings.stripe_cancel_url,
    )
    if not all(required):
        return None
    gateway = StripeGateway(
        secret_key=settings.stripe_secret_key or "",
        webhook_secret=settings.stripe_webhook_secret or "",
    )
    return StripeBillingService(
        repository=repository,
        gateway=gateway,
        success_url=settings.stripe_success_url or "",
        cancel_url=settings.stripe_cancel_url or "",
    )


def build_services(settings: AppSettings) -> AppServices:
    if not settings.api_key_pepper:
        raise ConfigurationError("API_KEY_PEPPER is required")
    engine = _engine(settings)
    Base.metadata.create_all(engine)

    tenants = TenantRepository(engine)
    billing = BillingRepository(engine)
    _seed_credit_packs(
        billing_repository=billing,
        serialized=settings.credit_packs_json,
    )
    rate_card = RateCard(
        managed_serp_credits=settings.managed_serp_credits,
        strict_serp_credits=settings.strict_serp_credits,
    )
    usage_meter = RankUsageMeter(
        billing_repository=billing,
        rate_card=rate_card,
    )

    return AppServices(
        tenant_repository=tenants,
        geo_repository=GeoRepository(engine),
        monitor_repository=MonitorRepository(engine),
        job_repository=JobRepository(engine),
        rank_repository=RankRepository(engine),
        api_keys=ApiKeyService(
            repository=tenants,
            pepper=settings.api_key_pepper,
        ),
        provider_registry=ProviderRegistry(
            managed=_managed_provider(settings),
            strict=_strict_provider(settings),
        ),
        billing_repository=billing,
        stripe_billing=_stripe_billing(
            settings=settings,
            repository=billing,
        ),
        usage_meter=usage_meter,
    )
