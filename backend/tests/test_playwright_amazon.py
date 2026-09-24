import json

import pytest

from amazon_geo_rank_monitor.domain.errors import UpstreamBlockedError
from amazon_geo_rank_monitor.providers.playwright_amazon import (
    PlaywrightAmazonBrowserClient,
    PlaywrightSessionFactory,
)
from amazon_geo_rank_monitor.providers.residential_proxy import BrowserProxyConfig


def proxy() -> BrowserProxyConfig:
    return BrowserProxyConfig(
        server="http://pr.oxylabs.io:7777",
        username="customer-user-cc-US-postalcode-10001-sessid-abc",
        password="secret",
    )


class StaticBodyLocator:
    def __init__(self, text: str) -> None:
        self.text = text

    async def inner_text(self):
        return self.text


class FakeManager:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.stopped = False

    async def start(self):
        return self.runtime

    async def stop(self):
        self.stopped = True


class FakeContext:
    def __init__(self, page) -> None:
        self.page = page
        self.closed = False

    async def new_page(self):
        return self.page

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, context) -> None:
        self.context = context
        self.context_kwargs = None
        self.closed = False

    async def new_context(self, **kwargs):
        self.context_kwargs = kwargs
        return self.context

    async def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser) -> None:
        self.browser = browser

    async def launch(self, **kwargs):
        return self.browser


class BasicPage:
    def __init__(self, body_text: str = "") -> None:
        self.body_text = body_text
        self.url = "about:blank"

    async def goto(self, url, **kwargs):
        self.url = url

    def locator(self, selector):
        if selector == "body":
            return StaticBodyLocator(self.body_text)
        raise AssertionError(selector)


class FakeSession:
    def __init__(self, page) -> None:
        self.page = page
        self.closed = False

    async def close(self):
        self.closed = True


class FakeSessionFactory:
    def __init__(self, page) -> None:
        self.session = FakeSession(page)

    async def __call__(self, proxy_config):
        return self.session


@pytest.mark.asyncio
async def test_session_factory_creates_isolated_context_with_proxy() -> None:
    page = BasicPage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    runtime = type(
        "Runtime",
        (),
        {"chromium": FakeChromium(browser)},
    )()
    manager = FakeManager(runtime)
    factory = PlaywrightSessionFactory(manager_factory=lambda: manager)

    session = await factory(proxy())

    proxy_config = browser.context_kwargs["proxy"]
    assert proxy_config["server"] == "http://pr.oxylabs.io:7777"
    assert proxy_config["username"].startswith("customer-user")
    assert proxy_config["password"] == "secret"
    assert browser.context_kwargs["locale"] == "en-US"

    await session.close()
    assert context.closed is True
    assert browser.closed is True
    assert manager.stopped is True


@pytest.mark.asyncio
async def test_verify_ip_location_prefers_maxmind_provider() -> None:
    payload = {
        "ip": "203.0.113.10",
        "providers": {
            "maxmind": {
                "country": "US",
                "city": "New York",
                "zip_code": "10001",
            },
            "ip2location": {
                "country": "US",
                "city": "New York City",
                "zip_code": "10011",
            },
        },
    }
    page = BasicPage(json.dumps(payload))
    factory = FakeSessionFactory(page)
    client = PlaywrightAmazonBrowserClient(
        proxy(),
        session_factory=factory,
    )

    async with client:
        location = await client.verify_ip_location()

    assert location.ip == "203.0.113.10"
    assert location.country == "US"
    assert location.city == "New York"
    assert location.postal_code == "10001"
    assert factory.session.closed is True


class ControlLocator:
    def __init__(self, *, text="", on_click=None, on_fill=None) -> None:
        self.text = text
        self.on_click = on_click
        self.on_fill = on_fill

    @property
    def first(self):
        return self

    async def click(self):
        if self.on_click:
            self.on_click()

    async def fill(self, value):
        if self.on_fill:
            self.on_fill(value)

    async def inner_text(self):
        return self.text


class DeliveryPage(BasicPage):
    def __init__(self) -> None:
        super().__init__("Amazon")
        self.filled_zip = None
        self.submitted = False

    async def wait_for_timeout(self, milliseconds):
        return None

    def locator(self, selector):
        if selector == "body":
            return StaticBodyLocator("Amazon")
        if selector == "#nav-global-location-popover-link":
            return ControlLocator()
        if selector == "#GLUXZipUpdateInput":
            return ControlLocator(
                on_fill=lambda value: setattr(self, "filled_zip", value)
            )
        if selector == "#GLUXZipUpdate input.a-button-input":
            return ControlLocator(
                on_click=lambda: setattr(self, "submitted", True)
            )
        if selector == "#glow-ingress-line2":
            return StaticBodyLocator(
                f"Deliver to New York {self.filled_zip}"
            )
        raise AssertionError(selector)


@pytest.mark.asyncio
async def test_set_delivery_location_confirms_requested_zip() -> None:
    page = DeliveryPage()
    client = PlaywrightAmazonBrowserClient(
        proxy(),
        session_factory=FakeSessionFactory(page),
    )

    async with client:
        confirmed = await client.set_delivery_location("10001")

    assert page.filled_zip == "10001"
    assert page.submitted is True
    assert confirmed == "10001"


class FakeCard:
    def __init__(self, asin: str, text: str) -> None:
        self.asin = asin
        self.text = text

    async def get_attribute(self, name: str):
        assert name == "data-asin"
        return self.asin

    async def inner_text(self):
        return self.text


class CardsLocator:
    def __init__(self, cards) -> None:
        self.cards = cards

    async def count(self):
        return len(self.cards)

    def nth(self, index):
        return self.cards[index]


class NoNextLocator:
    async def count(self):
        return 0


class SearchPage(BasicPage):
    def __init__(self, cards, body_text="Amazon Search") -> None:
        super().__init__(body_text)
        self.cards = cards

    def locator(self, selector):
        if selector == "body":
            return StaticBodyLocator(self.body_text)
        if (
            selector
            == '[data-component-type="s-search-result"][data-asin]'
        ):
            return CardsLocator(self.cards)
        if selector == "a.s-pagination-next:not(.s-pagination-disabled)":
            return NoNextLocator()
        raise AssertionError(selector)


@pytest.mark.asyncio
async def test_search_separates_sponsored_and_organic_cards() -> None:
    page = SearchPage(
        [
            FakeCard("B0AD000001", "Sponsored\nAd product"),
            FakeCard("B0ORGANIC1", "Organic one"),
            FakeCard("B0ORGANIC2", "Organic two"),
        ]
    )
    client = PlaywrightAmazonBrowserClient(
        proxy(),
        session_factory=FakeSessionFactory(page),
    )

    async with client:
        result = await client.search(
            keyword="walking pad",
            marketplace="amazon.com",
            search_depth=2,
        )

    assert [product.asin for product in result.organic_products] == [
        "B0ORGANIC1",
        "B0ORGANIC2",
    ]
    assert [product.position for product in result.organic_products] == [2, 3]
    assert [product.asin for product in result.sponsored_products] == [
        "B0AD000001"
    ]


@pytest.mark.asyncio
async def test_robot_check_is_blocked_not_empty_serp() -> None:
    page = SearchPage(
        [],
        body_text="Enter the characters you see below",
    )
    client = PlaywrightAmazonBrowserClient(
        proxy(),
        session_factory=FakeSessionFactory(page),
    )

    async with client:
        with pytest.raises(UpstreamBlockedError):
            await client.search(
                keyword="walking pad",
                marketplace="amazon.com",
                search_depth=10,
            )


class PagedNextLocator:
    def __init__(self, page) -> None:
        self.page = page

    @property
    def first(self):
        return self

    async def count(self):
        return int(self.page.page_index + 1 < len(self.page.pages))

    async def click(self):
        self.page.page_index += 1


class PagedSearchPage(SearchPage):
    def __init__(self, pages) -> None:
        super().__init__(pages[0])
        self.pages = pages
        self.page_index = 0

    async def wait_for_load_state(self, state):
        return None

    def locator(self, selector):
        if (
            selector
            == '[data-component-type="s-search-result"][data-asin]'
        ):
            return CardsLocator(self.pages[self.page_index])
        if selector == "a.s-pagination-next:not(.s-pagination-disabled)":
            return PagedNextLocator(self)
        return super().locator(selector)


@pytest.mark.asyncio
async def test_search_paginates_until_requested_organic_depth() -> None:
    page = PagedSearchPage(
        [
            [
                FakeCard("B0AD000001", "Sponsored\nAd"),
                FakeCard("B0ORGANIC1", "Organic 1"),
            ],
            [
                FakeCard("B0ORGANIC2", "Organic 2"),
                FakeCard("B0ORGANIC3", "Organic 3"),
            ],
        ]
    )
    client = PlaywrightAmazonBrowserClient(
        proxy(),
        session_factory=FakeSessionFactory(page),
    )

    async with client:
        result = await client.search(
            keyword="walking pad",
            marketplace="amazon.com",
            search_depth=3,
        )

    assert [product.asin for product in result.organic_products] == [
        "B0ORGANIC1",
        "B0ORGANIC2",
        "B0ORGANIC3",
    ]
    assert [product.page for product in result.organic_products] == [
        1,
        2,
        2,
    ]
