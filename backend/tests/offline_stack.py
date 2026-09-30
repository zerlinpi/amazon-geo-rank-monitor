"""Real application services with deterministic, network-free SERP fixtures."""

from amazon_geo_rank_monitor.application.provider_registry import ProviderRegistry
from amazon_geo_rank_monitor.config import AppSettings
from amazon_geo_rank_monitor.domain.models import SerpProduct, SerpResult, VerificationLevel
from amazon_geo_rank_monitor.notifications.email import MemoryEmailSender
from amazon_geo_rank_monitor.runtime import build_services
from amazon_geo_rank_monitor.workers.rank_worker import RankWorker


class OfflineProvider:
    provider_name = "offline-fixture"
    verification_level = VerificationLevel.MANAGED

    def __init__(self):
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        rank = {"10001": 5, "90001": 10, "60601": 15}.get(
            kwargs["geo_profile"].delivery_postal_code,
            5,
        )
        products = [SerpProduct(asin=f"FILLER{i:04}", position=i) for i in range(1, rank)]
        products += [
            SerpProduct(asin="B0TARGET01", position=rank),
            SerpProduct(asin="B0TARGET02", position=rank + 1),
        ]
        return SerpResult(organic_products=products)


class DisabledStrictProvider:
    provider_name = "disabled-offline"

    async def search(self, **kwargs):
        raise AssertionError("offline fixture must never request a strict proxy")


def build_offline_services(database_url):
    settings = AppSettings(
        _env_file=None,
        database_url=database_url,
        api_key_pepper="offline-test-only",
        auto_create_schema=True,
        allow_public_signup=True,
        redis_url=None,
        oxylabs_username=None,
        oxylabs_password=None,
        residential_proxy_username=None,
        residential_proxy_password=None,
        smtp_host=None,
        stripe_secret_key=None,
        auto_strict_verification_enabled=False,
    )
    services = build_services(settings)
    provider = OfflineProvider()
    services.provider_registry = ProviderRegistry(managed=provider, strict=DisabledStrictProvider())
    services.accounts._email_sender = MemoryEmailSender()
    return services, provider


def offline_worker(services):
    return RankWorker(
        job_repository=services.job_repository,
        rank_repository=services.rank_repository,
        provider_registry=services.provider_registry,
        tenant_repository=services.tenant_repository,
        billing_repository=services.billing_repository,
        rate_card=services.rate_card,
        worker_status_repository=services.worker_status_repository,
        probe_cache=services.probe_cache,
        competitive_intelligence=services.competitive_intelligence,
    )
