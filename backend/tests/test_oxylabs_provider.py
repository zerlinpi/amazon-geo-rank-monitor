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
        "page": 1,
        "last_visible_page": 1,
        "parse_status_code": 12000,
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
                    "last_visible_page": 2,
                    "parse_status_code": 12000,
                    "results": {"organic": [{"asin": "B0PAGE00001", "pos": 4}]},
                }
            ),
            SimpleNamespace(
                content={
                    "page": 2,
                    "last_visible_page": 2,
                    "parse_status_code": 12000,
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


class PagedAmazonClient:
    def __init__(self, counts, *, reverse=False):
        self.calls = []
        self.reverse = reverse
        self.contents = {}
        rank = 0
        for page, count in enumerate(counts, start=1):
            products = []
            for position in range(1, count + 1):
                rank += 1
                products.append({"asin": f"B0RANK{rank:04d}", "pos": position + 2})
            self.contents[page] = {
                "page": page, "last_visible_page": len(counts),
                "parse_status_code": 12000, "results": {"organic": products},
            }

    def scrape_search(self, query, **kwargs):
        self.calls.append(kwargs)
        pages = range(kwargs["start_page"], kwargs["start_page"] + kwargs["pages"])
        contents = [self.contents[p] for p in pages if p in self.contents]
        if self.reverse:
            contents.reverse()
        return SimpleNamespace(results=[SimpleNamespace(content=c) for c in contents])


async def search(provider, depth=100):
    return await provider.search(
        marketplace="amazon.com", keyword="trailer hitch", geo_profile=geo(),
        device="desktop", search_depth=depth,
    )


@pytest.mark.asyncio
async def test_collects_actual_organic_depth_when_pages_have_fewer_than_48_results():
    amazon = PagedAmazonClient([16] * 8)
    result = await search(OxylabsRankProvider(client=FakeClient(amazon)))
    assert len(result.organic_products) >= 100
    assert result.organic_products[99].asin == "B0RANK0100"
    requested = [p for call in amazon.calls for p in range(
        call["start_page"], call["start_page"] + call["pages"],
    )]
    assert requested == list(range(1, len(requested) + 1))


@pytest.mark.asyncio
async def test_reorders_provider_pages_before_deriving_organic_rank():
    amazon = PagedAmazonClient([48, 48, 48], reverse=True)
    result = await search(OxylabsRankProvider(client=FakeClient(amazon)))
    assert result.organic_products[0].asin == "B0RANK0001"
    assert result.organic_products[99].asin == "B0RANK0100"


@pytest.mark.asyncio
async def test_stops_when_provider_reports_the_last_available_page():
    amazon = PagedAmazonClient([16, 3])
    result = await search(OxylabsRankProvider(client=FakeClient(amazon)))
    assert len(result.organic_products) == 19
    assert len(amazon.calls) == 1


@pytest.mark.asyncio
async def test_missing_provider_page_cannot_be_reported_as_complete():
    amazon = PagedAmazonClient([48, 48, 48])
    del amazon.contents[2]
    with pytest.raises(ProviderResponseError, match="page"):
        await search(OxylabsRankProvider(client=FakeClient(amazon)))


@pytest.mark.asyncio
async def test_managed_page_limit_rejects_incomplete_depth():
    amazon = PagedAmazonClient([1] * 21)
    with pytest.raises(ProviderResponseError, match="depth.*page limit"):
        await search(OxylabsRankProvider(client=FakeClient(amazon)), depth=25)
    assert sum(call["pages"] for call in amazon.calls) <= 20


@pytest.mark.asyncio
async def test_paid_results_with_documented_relative_position_are_preserved():
    amazon = PagedAmazonClient([1])
    amazon.contents[1]["results"]["paid"] = [
        {"asin": "B0AD000001", "rel_pos": 2},
    ]
    result = await search(OxylabsRankProvider(client=FakeClient(amazon)), depth=1)
    assert result.sponsored_products[0].asin == "B0AD000001"


@pytest.mark.asyncio
async def test_invalid_organic_card_does_not_shift_later_products_up():
    amazon = PagedAmazonClient([2])
    amazon.contents[1]["results"]["organic"][0].pop("pos")
    with pytest.raises(ProviderResponseError, match="product"):
        await search(OxylabsRankProvider(client=FakeClient(amazon)), depth=2)


@pytest.mark.asyncio
async def test_documented_total_pages_marks_exhaustion():
    amazon = PagedAmazonClient([16, 3])
    for content in amazon.contents.values():
        content["pages"] = content.pop("last_visible_page")
    result = await search(OxylabsRankProvider(client=FakeClient(amazon)))
    assert len(result.organic_products) == 19
    assert len(amazon.calls) == 1


@pytest.mark.asyncio
async def test_contradictory_pagination_metadata_is_rejected():
    amazon = PagedAmazonClient([1, 1])
    amazon.contents[1]["pages"] = 1
    with pytest.raises(ProviderResponseError, match="page"):
        await search(OxylabsRankProvider(client=FakeClient(amazon)), depth=1)


@pytest.mark.asyncio
async def test_total_pages_takes_precedence_over_a_smaller_visible_page_window():
    amazon = PagedAmazonClient([2, 2, 2])
    for page, content in amazon.contents.items():
        content["pages"] = 3
        content["last_visible_page"] = page
    result = await search(OxylabsRankProvider(client=FakeClient(amazon)), depth=5)
    assert len(result.organic_products) == 6
    assert result.provider_metadata["search_exhausted"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("total_pages", [0, "2", True])
async def test_invalid_total_pages_cannot_confirm_exhaustion(total_pages):
    amazon = PagedAmazonClient([1])
    amazon.contents[1]["pages"] = total_pages
    with pytest.raises(ProviderResponseError, match="page"):
        await search(OxylabsRankProvider(client=FakeClient(amazon)), depth=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("parse_status", [None, 12002, 12003, 12004, 12005, 12006, 12007, 12008])
async def test_unsuccessful_or_unknown_parser_status_is_not_an_empty_success(parse_status):
    amazon = PagedAmazonClient([0])
    amazon.contents[1]["parse_status_code"] = parse_status
    with pytest.raises(ProviderResponseError, match="pars"):
        await search(OxylabsRankProvider(client=FakeClient(amazon)))
