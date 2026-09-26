from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from amazon_geo_rank_monitor.alerts import AlertService
from amazon_geo_rank_monitor.analytics import AnalyticsService
from amazon_geo_rank_monitor.api.app import AppServices
from amazon_geo_rank_monitor.api.rate_limit import build_rate_limiter
from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.auth.accounts import AccountService
from amazon_geo_rank_monitor.auth.api_keys import ApiKeyService
from amazon_geo_rank_monitor.auth.scim import ScimService
from amazon_geo_rank_monitor.auth.sso import OidcSsoService
from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.billing.stripe_service import StripeBillingService
from amazon_geo_rank_monitor.competitive import CompetitiveIntelligenceService
from amazon_geo_rank_monitor.config import (
    AppSettings,
    build_oxylabs_provider,
    build_residential_proxy_factory,
)
from amazon_geo_rank_monitor.domain.errors import ConfigurationError
from amazon_geo_rank_monitor.domain.models import VerificationLevel
from amazon_geo_rank_monitor.notifications.email import build_email_sender
from amazon_geo_rank_monitor.probe_cache import ProbeCacheService
from amazon_geo_rank_monitor.providers.playwright_amazon import (
    PlaywrightAmazonBrowserClient,
)
from amazon_geo_rank_monitor.providers.strict_browser import StrictBrowserRankProvider
from amazon_geo_rank_monitor.reports import ReportService
from amazon_geo_rank_monitor.repositories.account_repository import AccountRepository
from amazon_geo_rank_monitor.repositories.alert_repository import AlertRepository
from amazon_geo_rank_monitor.repositories.analytics_repository import AnalyticsRepository
from amazon_geo_rank_monitor.repositories.audit_repository import AuditRepository
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.competitive_repository import CompetitiveRepository
from amazon_geo_rank_monitor.repositories.geo_repository import GeoRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base
from amazon_geo_rank_monitor.repositories.monitor_repository import MonitorRepository
from amazon_geo_rank_monitor.repositories.probe_cache_repository import (
    ProbeCacheRepository,
)
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.report_repository import ReportRepository
from amazon_geo_rank_monitor.repositories.scim_repository import ScimRepository
from amazon_geo_rank_monitor.repositories.sso_repository import SsoRepository
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
    geo_repository = GeoRepository(engine)
    monitor_repository = MonitorRepository(engine)
    job_repository = JobRepository(
        engine,
        default_max_attempts=settings.job_max_attempts,
    )
    rank_repository = RankRepository(engine)
    probe_cache_repository = ProbeCacheRepository(engine)
    competitive_repository = CompetitiveRepository(engine)
    analytics_repository = AnalyticsRepository(engine)
    report_repository = ReportRepository(engine)
    accounts_repository = AccountRepository(engine)
    alert_repository = AlertRepository(engine)
    sso_repository = SsoRepository(engine)
    scim_repository = ScimRepository(engine)
    worker_status_repository = WorkerStatusRepository(engine)
    audit_repository = AuditRepository(engine)

    email_sender = build_email_sender(settings)
    accounts = AccountService(
        repository=accounts_repository,
        session_ttl_hours=settings.session_ttl_hours,
        invitation_ttl_hours=settings.invitation_ttl_hours,
        verification_ttl_hours=settings.email_verification_ttl_hours,
        password_reset_ttl_minutes=settings.password_reset_ttl_minutes,
        login_max_failures=settings.login_max_failures,
        login_lock_minutes=settings.login_lock_minutes,
        email_sender=email_sender,
        public_web_url=settings.public_web_url,
        mfa_encryption_key=settings.mfa_encryption_key or settings.api_key_pepper,
        mfa_issuer=settings.mfa_issuer,
        mfa_challenge_minutes=settings.mfa_challenge_minutes,
        trusted_device_days=settings.trusted_device_days,
        sso_repository=sso_repository,
    )
    sso = OidcSsoService(
        repository=sso_repository,
        account_repository=accounts_repository,
        accounts=accounts,
        encryption_key=(
            settings.sso_encryption_key
            or settings.mfa_encryption_key
            or settings.api_key_pepper
        ),
        callback_url=settings.sso_callback_url,
        public_web_url=settings.public_web_url,
        transaction_minutes=settings.sso_transaction_minutes,
    )
    scim = ScimService(
        repository=scim_repository,
        pepper=settings.scim_token_pepper or settings.api_key_pepper,
    )
    competitive_intelligence = CompetitiveIntelligenceService(
        repository=competitive_repository,
        monitor_repository=monitor_repository,
    )
    analytics = AnalyticsService(
        repository=analytics_repository,
        monitor_repository=monitor_repository,
    )
    reports = ReportService(
        repository=report_repository,
        analytics=analytics,
        monitor_repository=monitor_repository,
        competitive_repository=competitive_repository,
        email_sender=email_sender,
        encryption_key=(
            settings.report_encryption_key
            or settings.mfa_encryption_key
            or settings.api_key_pepper
        ),
    )
    alerts = AlertService(
        repository=alert_repository,
        rank_repository=rank_repository,
        job_repository=job_repository,
        monitor_repository=monitor_repository,
        email_sender=email_sender,
        encryption_key=(
            settings.alert_encryption_key
            or settings.mfa_encryption_key
            or settings.api_key_pepper
        ),
        webhook_allowed_hosts=settings.alert_webhook_allowed_host_list,
    )

    probe_cache = ProbeCacheService(
        repository=probe_cache_repository,
        managed_ttl_seconds=settings.probe_cache_managed_ttl_seconds,
        strict_ttl_seconds=settings.probe_cache_strict_ttl_seconds,
        retention_hours=settings.probe_cache_retention_hours,
    )

    billing = BillingRepository(engine)
    _seed_credit_packs(billing, settings)
    return AppServices(
        tenant_repository=tenants,
        geo_repository=geo_repository,
        monitor_repository=monitor_repository,
        job_repository=job_repository,
        rank_repository=rank_repository,
        probe_cache_repository=probe_cache_repository,
        probe_cache=probe_cache,
        competitive_repository=competitive_repository,
        competitive_intelligence=competitive_intelligence,
        api_keys=ApiKeyService(
            repository=tenants,
            pepper=settings.api_key_pepper,
        ),
        provider_registry=ProviderRegistry(
            managed=_managed_provider(settings),
            strict=_strict_provider(settings),
        ),
        alert_repository=alert_repository,
        alerts=alerts,
        analytics_repository=analytics_repository,
        analytics=analytics,
        report_repository=report_repository,
        reports=reports,
        billing_repository=billing,
        rate_card=RateCard(
            managed_serp=settings.managed_serp_credit_cost,
            browser_verified_serp=settings.strict_serp_credit_cost,
        ),
        stripe_billing=_stripe_billing(billing, settings),
        database_engine=engine,
        worker_status_repository=worker_status_repository,
        audit_repository=audit_repository,
        account_repository=accounts_repository,
        accounts=accounts,
        sso_repository=sso_repository,
        sso=sso,
        scim_repository=scim_repository,
        scim=scim,
        allow_public_signup=settings.allow_public_signup,
        session_cookie_name=settings.session_cookie_name,
        csrf_cookie_name=settings.csrf_cookie_name,
        trusted_device_cookie_name=settings.trusted_device_cookie_name,
        trusted_device_days=settings.trusted_device_days,
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
    )
