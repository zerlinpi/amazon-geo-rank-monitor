from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote_plus

from amazon_geo_rank_monitor.domain.errors import (
    ProviderResponseError,
    UpstreamBlockedError,
)
from amazon_geo_rank_monitor.domain.models import (
    ProxyLocation,
    SerpProduct,
    SerpResult,
)
from amazon_geo_rank_monitor.providers.residential_proxy import BrowserProxyConfig


class _OwnedPlaywrightSession:
    def __init__(
        self,
        *,
        manager: Any,
        browser: Any,
        context: Any,
        page: Any,
    ) -> None:
        self._manager = manager
        self._browser = browser
        self._context = context
        self.page = page

    async def close(self) -> None:
        try:
            await self._context.close()
        finally:
            try:
                await self._browser.close()
            finally:
                await self._manager.stop()


class PlaywrightSessionFactory:
    def __init__(
        self,
        *,
        manager_factory: Callable[[], Any] | None = None,
        headless: bool = True,
    ) -> None:
        self._manager_factory = manager_factory
        self._headless = headless

    async def __call__(
        self,
        proxy: BrowserProxyConfig,
    ) -> _OwnedPlaywrightSession:
        if self._manager_factory is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise ProviderResponseError(
                    "Playwright is not installed for strict verification"
                ) from exc
            manager = async_playwright()
        else:
            manager = self._manager_factory()

        runtime = await manager.start()
        browser = None
        context = None
        try:
            browser = await runtime.chromium.launch(headless=self._headless)
            context = await browser.new_context(
                proxy=proxy.to_playwright(),
                locale="en-US",
            )
            page = await context.new_page()
        except Exception:
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()
            await manager.stop()
            raise

        return _OwnedPlaywrightSession(
            manager=manager,
            browser=browser,
            context=context,
            page=page,
        )


SessionFactory = Callable[[BrowserProxyConfig], Awaitable[Any]]


class PlaywrightAmazonBrowserClient:
    LOCATION_URL = "https://ip.oxylabs.io/location"
    RESULT_SELECTOR = '[data-component-type="s-search-result"][data-asin]'
    NEXT_SELECTOR = "a.s-pagination-next:not(.s-pagination-disabled)"
    BLOCK_MARKERS = (
        "enter the characters you see below",
        "sorry, we just need to make sure you're not a robot",
    )

    def __init__(
        self,
        proxy: BrowserProxyConfig,
        *,
        session_factory: SessionFactory | None = None,
        max_pages: int = 20,
    ) -> None:
        self._proxy = proxy
        self._session_factory = session_factory or PlaywrightSessionFactory()
        self._session: Any | None = None
        self._page: Any | None = None
        self._max_pages = max_pages

    async def __aenter__(self) -> PlaywrightAmazonBrowserClient:
        self._session = await self._session_factory(self._proxy)
        self._page = self._session.page
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            await self._session.close()
        self._session = None
        self._page = None

    @property
    def page(self) -> Any:
        if self._page is None:
            raise RuntimeError(
                "browser client must be used as an async context manager"
            )
        return self._page

    async def verify_ip_location(self) -> ProxyLocation:
        await self.page.goto(self.LOCATION_URL, wait_until="domcontentloaded")
        body_text = await self.page.locator("body").inner_text()
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "proxy location endpoint returned invalid JSON"
            ) from exc
        return self._normalize_location(payload)

    async def set_delivery_location(self, postal_code: str) -> str | None:
        await self.page.goto(
            "https://www.amazon.com/",
            wait_until="domcontentloaded",
        )
        await self._assert_not_blocked()
        await self.page.locator("#nav-global-location-popover-link").click()
        await self.page.locator("#GLUXZipUpdateInput").fill(postal_code)
        submit = self.page.locator(
            "#GLUXZipUpdate input.a-button-input"
        ).first
        await submit.click()
        if hasattr(self.page, "wait_for_timeout"):
            await self.page.wait_for_timeout(500)
        delivery_text = await self.page.locator(
            "#glow-ingress-line2"
        ).inner_text()
        if postal_code.casefold() in delivery_text.casefold():
            return postal_code
        return None

    async def search(
        self,
        *,
        keyword: str,
        marketplace: str,
        search_depth: int,
    ) -> SerpResult:
        if search_depth < 1:
            raise ValueError("search_depth must be positive")

        base_url = self._marketplace_base_url(marketplace)
        search_url = f"{base_url}/s?k={quote_plus(keyword)}"
        await self.page.goto(search_url, wait_until="domcontentloaded")

        organic: list[SerpProduct] = []
        sponsored: list[SerpProduct] = []
        absolute: list[SerpProduct] = []
        mixed_position = 0
        page_number = 1
        page_limit = min(self._max_pages, search_depth)

        while page_number <= page_limit:
            await self._assert_not_blocked()
            cards = self.page.locator(self.RESULT_SELECTOR)
            card_count = await cards.count()

            for index in range(card_count):
                if len(organic) >= search_depth:
                    break

                card = cards.nth(index)
                asin = (
                    await card.get_attribute("data-asin") or ""
                ).strip().upper()
                if not asin:
                    continue

                mixed_position += 1
                text = await card.inner_text()
                is_sponsored = "sponsored" in text.casefold()
                product = SerpProduct(
                    asin=asin,
                    position=mixed_position,
                    page=page_number,
                    sponsored=is_sponsored,
                )
                absolute.append(product)
                if is_sponsored:
                    sponsored.append(product)
                else:
                    organic.append(product)

            if len(organic) >= search_depth:
                break

            next_link = self.page.locator(self.NEXT_SELECTOR)
            if await next_link.count() == 0:
                break

            await next_link.first.click()
            if hasattr(self.page, "wait_for_load_state"):
                await self.page.wait_for_load_state("domcontentloaded")
            page_number += 1

        return SerpResult(
            organic_products=organic,
            sponsored_products=sponsored,
            absolute_products=absolute,
            provider_metadata={
                "browser": "playwright",
                "pages_scanned": page_number,
            },
        )

    async def _assert_not_blocked(self) -> None:
        url = str(getattr(self.page, "url", "")).casefold()
        if "validatecaptcha" in url:
            raise UpstreamBlockedError(
                "Amazon robot/CAPTCHA challenge detected"
            )

        body = (await self.page.locator("body").inner_text()).casefold()
        if any(marker in body for marker in self.BLOCK_MARKERS):
            raise UpstreamBlockedError(
                "Amazon robot/CAPTCHA challenge detected"
            )

    @staticmethod
    def _marketplace_base_url(marketplace: str) -> str:
        normalized = marketplace.strip().lower()
        if not normalized.startswith("amazon."):
            raise ProviderResponseError(
                f"unsupported Amazon marketplace: {marketplace}"
            )
        return f"https://www.{normalized}"

    @staticmethod
    def _normalize_location(payload: Any) -> ProxyLocation:
        if not isinstance(payload, dict):
            raise ProviderResponseError(
                "proxy location response must be an object"
            )

        providers = payload.get("providers")
        if not isinstance(providers, dict):
            raise ProviderResponseError(
                "proxy location response is missing providers"
            )

        selected = providers.get("maxmind")
        if not isinstance(selected, dict):
            selected = next(
                (
                    value
                    for value in providers.values()
                    if isinstance(value, dict)
                ),
                None,
            )
        if not isinstance(selected, dict):
            raise ProviderResponseError(
                "proxy location response has no usable provider"
            )

        return ProxyLocation(
            ip=payload.get("ip"),
            country=selected.get("country"),
            state=selected.get("state") or selected.get("region"),
            city=selected.get("city"),
            postal_code=(
                selected.get("zip_code")
                or selected.get("postal_code")
                or selected.get("postcode")
            ),
        )
