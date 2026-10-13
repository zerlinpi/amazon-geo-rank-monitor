from __future__ import annotations

import asyncio
import math
from collections.abc import Iterable
from typing import Any

from amazon_geo_rank_monitor.domain.errors import (
    ProviderResponseError,
    ProviderUnavailableError,
)
from amazon_geo_rank_monitor.domain.models import (
    GeoProfile,
    SerpProduct,
    SerpResult,
    VerificationLevel,
)


class OxylabsRankProvider:
    """Adapter for Oxylabs managed Amazon Search results.

    Managed mode uses Amazon delivery geography through geo_location. The
    requested IP geography is preserved as metadata only; strict IP+delivery
    verification belongs to the browser provider in the next phase.
    """

    provider_name = "oxylabs"
    cache_version = 2
    verification_level = VerificationLevel.MANAGED

    def __init__(self, client: Any, *, estimated_results_per_page: int = 48) -> None:
        self._client = client
        self._estimated_results_per_page = estimated_results_per_page
        self._max_pages = 20

    async def search(
        self,
        *,
        marketplace: str,
        keyword: str,
        geo_profile: GeoProfile,
        device: str,
        search_depth: int,
    ) -> SerpResult:
        if search_depth < 1:
            raise ValueError("search_depth must be positive")
        domain = self._domain_for_marketplace(marketplace)
        pages = max(1, math.ceil(search_depth / self._estimated_results_per_page))
        kwargs = {
            "domain": domain,
            "geo_location": geo_profile.delivery_postal_code,
            "user_agent_type": device,
            "parse": True,
        }
        organic: list[SerpProduct] = []
        sponsored: list[SerpProduct] = []
        absolute: list[SerpProduct] = []
        start_page = 1
        pages_requested = 0
        pages_scanned = 0
        last_available_page: int | None = None
        while len(organic) < search_depth:
            if start_page > self._max_pages:
                raise ProviderResponseError(
                    "Managed search depth was not reached before the page limit"
                )
            pages = min(pages, self._max_pages - start_page + 1)
            if last_available_page is not None:
                pages = min(pages, last_available_page - start_page + 1)
            pages_requested += pages
            try:
                response = await asyncio.to_thread(
                    self._client.amazon.scrape_search, keyword,
                    **kwargs, start_page=start_page, pages=pages,
                )
            except Exception as exc:
                raise ProviderUnavailableError(
                    f"Oxylabs Amazon search failed ({type(exc).__name__})"
                ) from exc

            try:
                contents = [item.content for item in response.results]
            except (AttributeError, TypeError) as exc:
                raise ProviderResponseError("Oxylabs response is missing parsed results") from exc
            if not contents:
                raise ProviderResponseError("Oxylabs response contained no result payloads")

            by_page = {}
            for content in contents:
                self._result_block(content)
                page = self._page_number(content)
                if page in by_page or not start_page <= page < start_page + pages:
                    raise ProviderResponseError("Oxylabs returned duplicate or unexpected pages")
                by_page[page] = content
                last_page = self._last_page(content, page)
                if last_page is not None:
                    last_available_page = max(last_available_page or 0, last_page)

            expected_end = start_page + pages - 1
            if last_available_page is not None:
                expected_end = min(expected_end, last_available_page)
            if set(by_page) != set(range(start_page, expected_end + 1)):
                raise ProviderResponseError("Oxylabs response is missing requested pages")

            for page, content in sorted(by_page.items()):
                result_block = self._result_block(content)
                organic.extend(self._parse_products(
                    result_block["organic"], sponsored=False, default_page=page,
                ))
                paid_items = result_block.get("paid", result_block.get("sponsored", []))
                sponsored.extend(self._parse_products(
                    paid_items, sponsored=True, default_page=page,
                ))
                absolute.extend(self._parse_products(
                    result_block.get("items", []), sponsored=None, default_page=page,
                ))
            pages_scanned += len(by_page)
            start_page = expected_end + 1
            if last_available_page is not None and expected_end >= last_available_page:
                break
            if not organic:
                raise ProviderResponseError(
                    "Oxylabs empty results do not confirm the last available page"
                )
            # Page sizes vary by query and marketplace. Continue using observed
            # organic counts rather than treating an estimate as search coverage.
            pages = max(1, math.ceil((search_depth - len(organic)) * pages_scanned / len(organic)))

        return SerpResult(
            organic_products=organic,
            sponsored_products=sponsored,
            absolute_products=absolute,
            provider_metadata={
                "provider": self.provider_name,
                "marketplace": marketplace,
                "domain": domain,
                "pages_requested": pages_requested,
                "pages_scanned": pages_scanned,
                "organic_results": len(organic),
                "search_exhausted": (
                    last_available_page is not None and pages_scanned >= last_available_page
                ),
            },
            geo_metadata={
                "delivery_postal_code": geo_profile.delivery_postal_code,
                "requested_ip_country": geo_profile.ip_country,
                "requested_ip_state": geo_profile.ip_state,
                "requested_ip_city": geo_profile.ip_city,
                "requested_ip_postal_code": geo_profile.ip_postal_code,
                "ip_geography_verified": False,
            },
        )

    @staticmethod
    def _domain_for_marketplace(marketplace: str) -> str:
        normalized = marketplace.strip().lower()
        if normalized.startswith("amazon."):
            return normalized.removeprefix("amazon.")
        raise ProviderResponseError(f"unsupported Amazon marketplace: {marketplace}")

    @staticmethod
    def _result_block(content: Any) -> dict[str, Any]:
        if not isinstance(content, dict):
            raise ProviderResponseError("Oxylabs content must be an object")
        if content.get("parse_status_code") != 12000:
            raise ProviderResponseError("Oxylabs response was not successfully parsed")
        results = content.get("results")
        if not isinstance(results, dict) or not isinstance(results.get("organic"), list):
            raise ProviderResponseError("Oxylabs parsed response is missing results.organic")
        return results

    @staticmethod
    def _last_page(content: dict[str, Any], page: int) -> int | None:
        total = content.get("pages")
        visible = content.get("last_visible_page")
        for value in (total, visible):
            if value is not None and (type(value) is not int or value < page):
                raise ProviderResponseError("Oxylabs response has invalid page metadata")
        if total is not None and visible is not None and visible > total:
            raise ProviderResponseError("Oxylabs response has contradictory page metadata")
        # The documented total takes precedence over a smaller pagination window.
        return total if total is not None else visible

    @staticmethod
    def _page_number(content: Any) -> int:
        if isinstance(content, dict):
            page = content.get("page", 1)
            if isinstance(page, int) and page >= 1:
                return page
        return 1

    @staticmethod
    def _parse_products(
        items: Iterable[Any],
        sponsored: bool | None,
        *,
        default_page: int = 1,
    ) -> list[SerpProduct]:
        products: list[SerpProduct] = []
        if not isinstance(items, list):
            raise ProviderResponseError("Oxylabs product collection must be a list")
        for item in items:
            if not isinstance(item, dict):
                if sponsored is False:
                    raise ProviderResponseError("Oxylabs organic product must be an object")
                continue
            asin = item.get("asin")
            position = item.get("pos", item.get("position", item.get("rel_pos")))
            if not asin or type(position) is not int or position < 1:
                if sponsored is False:
                    raise ProviderResponseError(
                        "Oxylabs organic product has no valid ASIN/position"
                    )
                continue
            is_sponsored = (
                bool(item.get("is_sponsored", False))
                if sponsored is None
                else sponsored
            )
            products.append(
                SerpProduct(
                    asin=str(asin),
                    position=position,
                    page=int(item.get("page", default_page) or default_page),
                    sponsored=is_sponsored,
                    title=item.get("title"),
                )
            )
        return products
