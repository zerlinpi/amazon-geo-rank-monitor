from __future__ import annotations

import asyncio
import math
from collections.abc import Iterable
from typing import Any

from amazon_geo_rank_monitor.domain.errors import (
    ProviderResponseError,
    ProviderUnavailableError,
)
from amazon_geo_rank_monitor.domain.models import GeoProfile, SerpProduct, SerpResult


class OxylabsRankProvider:
    """Adapter for Oxylabs managed Amazon Search results.

    Managed mode uses Amazon delivery geography through geo_location. The
    requested IP geography is preserved as metadata only; strict IP+delivery
    verification belongs to the browser provider in the next phase.
    """

    provider_name = "oxylabs"

    def __init__(self, client: Any, *, estimated_results_per_page: int = 48) -> None:
        self._client = client
        self._estimated_results_per_page = estimated_results_per_page

    async def search(
        self,
        *,
        marketplace: str,
        keyword: str,
        geo_profile: GeoProfile,
        device: str,
        search_depth: int,
    ) -> SerpResult:
        domain = self._domain_for_marketplace(marketplace)
        pages = max(1, math.ceil(search_depth / self._estimated_results_per_page))
        kwargs = {
            "domain": domain,
            "geo_location": geo_profile.delivery_postal_code,
            "user_agent_type": device,
            "parse": True,
            "start_page": 1,
            "pages": pages,
        }
        try:
            response = await asyncio.to_thread(
                self._client.amazon.scrape_search,
                keyword,
                **kwargs,
            )
        except Exception as exc:
            raise ProviderUnavailableError(f"Oxylabs Amazon search failed: {exc}") from exc

        try:
            contents = [item.content for item in response.results]
        except (AttributeError, TypeError) as exc:
            raise ProviderResponseError("Oxylabs response is missing parsed results") from exc

        if not contents:
            raise ProviderResponseError("Oxylabs response contained no result payloads")

        organic: list[SerpProduct] = []
        sponsored: list[SerpProduct] = []
        absolute: list[SerpProduct] = []
        for content in contents:
            result_block = self._result_block(content)
            page = self._page_number(content)
            organic.extend(
                self._parse_products(
                    result_block.get("organic", []),
                    sponsored=False,
                    default_page=page,
                )
            )
            paid_items = result_block.get("paid", result_block.get("sponsored", []))
            sponsored.extend(
                self._parse_products(
                    paid_items,
                    sponsored=True,
                    default_page=page,
                )
            )
            absolute.extend(
                self._parse_products(
                    result_block.get("items", []),
                    sponsored=None,
                    default_page=page,
                )
            )

        return SerpResult(
            organic_products=organic,
            sponsored_products=sponsored,
            absolute_products=absolute,
            provider_metadata={
                "provider": self.provider_name,
                "marketplace": marketplace,
                "domain": domain,
                "pages_requested": pages,
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
        results = content.get("results")
        if not isinstance(results, dict) or "organic" not in results:
            raise ProviderResponseError("Oxylabs parsed response is missing results.organic")
        return results

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
        for item in items:
            if not isinstance(item, dict):
                continue
            asin = item.get("asin")
            position = item.get("pos", item.get("position"))
            if not asin or not isinstance(position, int) or position < 1:
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
