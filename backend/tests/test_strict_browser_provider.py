from decimal import Decimal

import pytest

from amazon_geo_rank_monitor.domain.errors import (
    GeoVerificationError,
    UpstreamBlockedError,
)
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    ProxyLocation,
    SerpProduct,
    SerpResult,
)
from amazon_geo_rank_monitor.providers.residential_proxy import (
    OxylabsResidentialProxyFactory,
)
from amazon_geo_rank_monitor.providers.strict_browser import (
    StrictBrowserRankProvider,
)


def geo() -> GeoProfile:
    return GeoProfile(
        id="us-ny-10001",
        name="New York",
        marketplace="amazon.com",
        ip_country="US",
        ip_state="NY",
        ip_city="New York",
        ip_postal_code="10001",
        delivery_country="US",
        delivery_postal_code="10001",
        device="desktop",
        weight=Decimal("1"),
    )


class FakeBrowserClient:
    def __init__(
        self,
        *,
        location: ProxyLocation,
        confirmed_zip: str | None,
        result: SerpResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.location = location
        self.confirmed_zip = confirmed_zip
        self.result = result or SerpResult(
            organic_products=[SerpProduct(asin="B0TARGET01", position=3)]
        )
        self.error = error
        self.closed = False
        self.delivery_calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True

    async def verify_ip_location(self) -> ProxyLocation:
        return self.location

    async def set_delivery_location(self, postal_code: str) -> str | None:
        self.delivery_calls.append(postal_code)
        return self.confirmed_zip

    async def search(
        self,
        *,
        keyword: str,
        marketplace: str,
        search_depth: int,
    ) -> SerpResult:
        if self.error:
            raise self.error
        return self.result


class BrowserFactory:
    def __init__(self, client: FakeBrowserClient) -> None:
        self.client = client
        self.proxies = []

    def __call__(self, proxy):
        self.proxies.append(proxy)
        return self.client


@pytest.mark.asyncio
async def test_strict_provider_verifies_ip_and_delivery_before_returning_serp() -> None:
    client = FakeBrowserClient(
        location=ProxyLocation(
            ip="203.0.113.10",
            country="US",
            state="NY",
            city="New York",
            postal_code="10001",
        ),
        confirmed_zip="10001",
    )
    browser_factory = BrowserFactory(client)
    provider = StrictBrowserRankProvider(
        proxy_factory=OxylabsResidentialProxyFactory(
            username="user",
            password="secret",
        ),
        browser_client_factory=browser_factory,
        session_id_factory=lambda: "session123",
    )

    result = await provider.search(
        marketplace="amazon.com",
        keyword="walking pad",
        geo_profile=geo(),
        device="desktop",
        search_depth=100,
    )

    assert len(browser_factory.proxies) == 1
    assert client.delivery_calls == ["10001"]
    assert client.closed is True
    assert result.geo_metadata["verification_level"] == "strict"
    assert result.geo_metadata["ip_geography_verified"] is True
    assert result.geo_metadata["delivery_geography_verified"] is True
    assert result.geo_metadata["observed_ip_postal_code"] == "10001"
    assert result.geo_metadata["confirmed_delivery_postal_code"] == "10001"
    assert "secret" not in repr(result.geo_metadata)


@pytest.mark.asyncio
async def test_strict_provider_fails_when_proxy_postal_code_mismatches() -> None:
    client = FakeBrowserClient(
        location=ProxyLocation(country="US", state="CA", postal_code="90001"),
        confirmed_zip="10001",
    )
    provider = StrictBrowserRankProvider(
        proxy_factory=OxylabsResidentialProxyFactory(
            username="user",
            password="secret",
        ),
        browser_client_factory=BrowserFactory(client),
        session_id_factory=lambda: "session123",
    )
    with pytest.raises(GeoVerificationError):
        await provider.search(
            marketplace="amazon.com",
            keyword="walking pad",
            geo_profile=geo(),
            device="desktop",
            search_depth=100,
        )
    assert client.closed is True


@pytest.mark.asyncio
async def test_strict_provider_fails_when_delivery_zip_is_not_confirmed() -> None:
    client = FakeBrowserClient(
        location=ProxyLocation(
            country="US",
            state="NY",
            city="New York",
            postal_code="10001",
        ),
        confirmed_zip="11201",
    )
    provider = StrictBrowserRankProvider(
        proxy_factory=OxylabsResidentialProxyFactory(
            username="user",
            password="secret",
        ),
        browser_client_factory=BrowserFactory(client),
        session_id_factory=lambda: "session123",
    )
    with pytest.raises(GeoVerificationError):
        await provider.search(
            marketplace="amazon.com",
            keyword="walking pad",
            geo_profile=geo(),
            device="desktop",
            search_depth=100,
        )


@pytest.mark.asyncio
async def test_strict_provider_propagates_blocked_error() -> None:
    client = FakeBrowserClient(
        location=ProxyLocation(
            country="US",
            state="NY",
            city="New York",
            postal_code="10001",
        ),
        confirmed_zip="10001",
        error=UpstreamBlockedError("robot check"),
    )
    provider = StrictBrowserRankProvider(
        proxy_factory=OxylabsResidentialProxyFactory(
            username="user",
            password="secret",
        ),
        browser_client_factory=BrowserFactory(client),
        session_id_factory=lambda: "session123",
    )
    with pytest.raises(UpstreamBlockedError):
        await provider.search(
            marketplace="amazon.com",
            keyword="walking pad",
            geo_profile=geo(),
            device="desktop",
            search_depth=100,
        )


@pytest.mark.asyncio
async def test_strict_zip_verification_rejects_non_us_marketplace() -> None:
    profile = geo().model_copy(
        update={
            "marketplace": "amazon.co.uk",
            "ip_country": "GB",
            "ip_state": None,
            "ip_city": None,
            "ip_postal_code": None,
            "delivery_country": "GB",
            "delivery_postal_code": "SW1A 1AA",
        }
    )
    client = FakeBrowserClient(
        location=ProxyLocation(country="GB"),
        confirmed_zip="SW1A 1AA",
    )
    provider = StrictBrowserRankProvider(
        proxy_factory=OxylabsResidentialProxyFactory(
            username="user",
            password="secret",
        ),
        browser_client_factory=BrowserFactory(client),
        session_id_factory=lambda: "session123",
    )
    with pytest.raises(GeoVerificationError):
        await provider.search(
            marketplace="amazon.co.uk",
            keyword="walking pad",
            geo_profile=profile,
            device="desktop",
            search_depth=100,
        )
