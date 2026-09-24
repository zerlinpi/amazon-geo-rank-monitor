from decimal import Decimal
from types import SimpleNamespace

import pytest

from amazon_geo_rank_monitor.domain.errors import (
    ProviderResponseError,
    ProviderUnavailableError,
)
from amazon_geo_rank_monitor.domain.models import GeoProfile
from amazon_geo_rank_monitor.providers.oxylabs import OxylabsRankProvider


class FakeAmazonClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def scrape_search(self, query: str, **kwargs):
        self.calls.append((query, kwargs))
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, amazon: FakeAmazonClient) -> None:
        self.amazon = amazon


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
        weight=Decimal("30"),
    )


@pytest.mark.asyncio
async def test_builds_managed_amazon_search_and_normalizes_results() -> None:
    content = {
        "results": {
            "organic": [
                {"asin": "b0target01", "pos": 2, "page": 1, "title": "Target"},
            ],
            "paid": [
                {"asin": "b0ad000001", "pos": 1, "page": 1, "title": "Ad"},
            ],
            "items": [
                {"asin": "b0ad000001", "pos": 1, "page": 1, "is_sponsored": True},
                {"asin": "b0target01", "pos": 3, "page": 1, "is_sponsored": False},
            ],
        }
    }
    response = SimpleNamespace(results=[SimpleNamespace(content=content)])
    amazon = FakeAmazonClient(response=response)
    provider = OxylabsRankProvider(client=FakeClient(amazon))

    result = await provider.search(
        marketplace="amazon.com",
        keyword="walking pad",
        geo_profile=geo(),
        device="desktop",
        search_depth=100,
    )

    assert len(amazon.calls) == 1
    query, kwargs = amazon.calls[0]
    assert query == "walking pad"
    assert kwargs["domain"] == "com"
    assert kwargs["geo_location"] == "10001"
    assert kwargs["user_agent_type"] == "desktop"
    assert kwargs["parse"] is True
    assert kwargs["start_page"] == 1
    assert kwargs["pages"] == 3
    assert result.organic_products[0].asin == "B0TARGET01"
    assert result.sponsored_products[0].asin == "B0AD000001"
    assert result.absolute_products[1].position == 3
    assert result.geo_metadata["delivery_postal_code"] == "10001"
    assert result.geo_metadata["requested_ip_postal_code"] == "10001"


@pytest.mark.asyncio
async def test_malformed_response_raises_provider_response_error() -> None:
    response = SimpleNamespace(results=[SimpleNamespace(content={"unexpected": {}})])
    provider = OxylabsRankProvider(client=FakeClient(FakeAmazonClient(response=response)))
    with pytest.raises(ProviderResponseError):
        await provider.search(
            marketplace="amazon.com",
            keyword="walking pad",
            geo_profile=geo(),
            device="desktop",
            search_depth=50,
        )


@pytest.mark.asyncio
async def test_client_failure_is_not_converted_to_empty_serp() -> None:
    provider = OxylabsRankProvider(
        client=FakeClient(FakeAmazonClient(error=TimeoutError("provider timeout")))
    )
    with pytest.raises(ProviderUnavailableError):
        await provider.search(
            marketplace="amazon.com",
            keyword="walking pad",
            geo_profile=geo(),
            device="desktop",
            search_depth=50,
        )


@pytest.mark.asyncio
async def test_preserves_page_number_from_each_oxylabs_payload() -> None:
    response = SimpleNamespace(
        results=[
            SimpleNamespace(
                content={
                    "page": 1,
                    "results": {"organic": [{"asin": "B0PAGE00001", "pos": 4}]},
                }
            ),
            SimpleNamespace(
                content={
                    "page": 2,
                    "results": {"organic": [{"asin": "B0PAGE00002", "pos": 3}]},
                }
            ),
        ]
    )
    provider = OxylabsRankProvider(client=FakeClient(FakeAmazonClient(response=response)))
    result = await provider.search(
        marketplace="amazon.com",
        keyword="walking pad",
        geo_profile=geo(),
        device="desktop",
        search_depth=100,
    )
    assert [p.page for p in result.organic_products] == [1, 2]
