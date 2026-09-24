from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from amazon_geo_rank_monitor.domain.errors import GeoVerificationError
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    GeoVerificationResult,
    ProxyLocation,
    SerpResult,
)
from amazon_geo_rank_monitor.providers.browser_client import AmazonBrowserClient
from amazon_geo_rank_monitor.providers.residential_proxy import (
    BrowserProxyConfig,
    OxylabsResidentialProxyFactory,
)

BrowserClientFactory = Callable[[BrowserProxyConfig], AmazonBrowserClient]


class StrictBrowserRankProvider:
    provider_name = "strict_browser"

    def __init__(
        self,
        *,
        proxy_factory: OxylabsResidentialProxyFactory,
        browser_client_factory: BrowserClientFactory,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._proxy_factory = proxy_factory
        self._browser_client_factory = browser_client_factory
        self._session_id_factory = session_id_factory or (lambda: uuid4().hex)

    async def search(
        self,
        *,
        marketplace: str,
        keyword: str,
        geo_profile: GeoProfile,
        device: str,
        search_depth: int,
    ) -> SerpResult:
        if marketplace.strip().lower() != "amazon.com":
            raise GeoVerificationError(
                "strict delivery ZIP verification currently supports amazon.com only"
            )
        session_id = self._session_id_factory()
        proxy = self._proxy_factory.build(geo_profile, session_id=session_id)
        client = self._browser_client_factory(proxy)

        async with client:
            observed_ip = await client.verify_ip_location()
            precheck = self._verification(
                geo_profile=geo_profile,
                observed_ip=observed_ip,
                confirmed_delivery_postal_code=None,
            )
            if not precheck.ip_verified:
                raise GeoVerificationError(
                    f"proxy geography does not match geo profile {geo_profile.id}"
                )

            confirmed_zip = await client.set_delivery_location(
                geo_profile.delivery_postal_code
            )
            verification = self._verification(
                geo_profile=geo_profile,
                observed_ip=observed_ip,
                confirmed_delivery_postal_code=confirmed_zip,
            )
            if not verification.delivery_verified:
                raise GeoVerificationError(
                    f"Amazon delivery location was not confirmed for {geo_profile.id}"
                )

            result = await client.search(
                keyword=keyword,
                marketplace=marketplace,
                search_depth=search_depth,
            )

        result.provider_metadata.update(
            {
                "provider": self.provider_name,
                "verification_level": "strict",
                "session_id": session_id,
            }
        )
        result.geo_metadata.update(
            {
                "verification_level": "strict",
                "requested_ip_country": geo_profile.ip_country,
                "requested_ip_state": geo_profile.ip_state,
                "requested_ip_city": geo_profile.ip_city,
                "requested_ip_postal_code": geo_profile.ip_postal_code,
                "observed_ip": observed_ip.ip,
                "observed_ip_country": observed_ip.country,
                "observed_ip_state": observed_ip.state,
                "observed_ip_city": observed_ip.city,
                "observed_ip_postal_code": observed_ip.postal_code,
                "ip_geography_verified": verification.ip_verified,
                "requested_delivery_postal_code": geo_profile.delivery_postal_code,
                "confirmed_delivery_postal_code": confirmed_zip,
                "delivery_geography_verified": verification.delivery_verified,
                "strict_verified": verification.strict_verified,
            }
        )
        return result

    @staticmethod
    def _verification(
        *,
        geo_profile: GeoProfile,
        observed_ip: ProxyLocation,
        confirmed_delivery_postal_code: str | None,
    ) -> GeoVerificationResult:
        return GeoVerificationResult(
            requested_ip_country=geo_profile.ip_country,
            requested_ip_state=geo_profile.ip_state,
            requested_ip_city=geo_profile.ip_city,
            requested_ip_postal_code=geo_profile.ip_postal_code,
            observed_ip=observed_ip,
            requested_delivery_postal_code=geo_profile.delivery_postal_code,
            confirmed_delivery_postal_code=confirmed_delivery_postal_code,
        )
