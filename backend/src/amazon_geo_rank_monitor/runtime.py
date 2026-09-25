from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.api.app import AppServices
from amazon_geo_rank_monitor.api.rate_limit import build_rate_limiter
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.accounts import AccountService
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.billing.stripe_service import StripeBillingService
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
from amazon_geo_rank_monitor.repositories.account_repository import AccountRepository
from amazon_geo_rank_monitor.repositories.audit_repository import AuditRepository
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository
from amazon_geo_rank_monitor.repositories.worker_status_repository import (
    WorkerStatusRepository,
)


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


def _seed_credit_packs(repository: BillingRepository, settings: AppSettings) -> None:
    packs = [
        (
            "starter",
            "Starter Credits",
            settings.credit_pack_starter_credits,
            settings.credit_pack_starter_amount_minor,
        ),
        (
            "growth",
            "Growth Credits",
            settings.credit_pack_growth_credits,
            settings.credit_pack_growth_amount_minor,
        ),
        (
            "scale",
            "Scale Credits",
            settings.credit_pack_scale_credits,
            settings.credit_pack_scale_amount_minor,
        ),
    ]
    for pack_id, name, credits, amount_minor in packs:
        if amount_minor > 0:
            repository.upsert_credit_pack(
                pack_id=pack_id,
                name=name,
                credits=credits,
                amount_minor=amount_minor,
                currency=settings.billing_currency,
            )


def _stripe_billing(repository: BillingRepository, settings: AppSettings):
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        return None
    return StripeBillingService(
        repository=repository,
        secret_key=settings.stripe_secret_key,
        webhook_secret=settings.stripe_webhook_secret,
        success_url=settings.stripe_success_url,
        cancel_url=settings.stripe_cancel_url,
    )


def build_services(settings: AppSettings) -> AppServices:
    if not settings.api_key_pepper:
        raise ConfigurationError("API_KEY_PEPPER is required")
    engine = _engine(settings)
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)

    tenants = TenantRepository(engine)
    accounts_repository = AccountRepository(engine)
    billing = BillingRepository(engine)
    _seed_credit_packs(billing, settings)
    return AppServices(
        tenant_repository=tenants,
        geo_repository=GeoRepository(engine),
        monitor_repository=MonitorRepository(engine),
        job_repository=JobRepository(
            engine,
            default_max_attempts=settings.job_max_attempts,
        ),
        rank_repository=RankRepository(engine),
        api_keys=ApiKeyService(
            repository=tenants,
            pepper=settings.api_key_pepper,
        ),
        billing_repository=billing,
        rate_card=RateCard(
            managed_serp=settings.managed_serp_credit_cost,
            browser_verified_serp=settings.strict_serp_credit_cost,
        ),
        stripe_billing=_stripe_billing(billing, settings),
        database_engine=engine,
        worker_status_repository=WorkerStatusRepository(engine),
        audit_repository=AuditRepository(engine),
        account_repository=accounts_repository,
        accounts=AccountService(
            repository=accounts_repository,
            session_ttl_hours=settings.session_ttl_hours,
            invitation_ttl_hours=settings.invitation_ttl_hours,
        ),
        allow_public_signup=settings.allow_public_signup,
        session_cookie_name=settings.session_cookie_name,
        csrf_cookie_name=settings.csrf_cookie_name,
        session_cookie_secure=settings.session_cookie_secure,
        session_cookie_samesite=settings.session_cookie_samesite,
        rate_limiter=build_rate_limiter(
            requests_per_minute=settings.api_rate_limit_per_minute,
            redis_url=settings.redis_url,
        ),
        auth_rate_limiter=build_rate_limiter(
            requests_per_minute=settings.auth_rate_limit_per_minute,
            redis_url=settings.redis_url,
            namespace="agrm:auth",
        ),
        provider_registry=ProviderRegistry(
            managed=_managed_provider(settings),
            strict=_strict_provider(settings),
        ),
    )
