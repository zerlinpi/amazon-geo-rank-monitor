from __future__ import annotations

from typing import Protocol

from amazon_geo_rank_monitor.domain.models import ProxyLocation, SerpResult


class AmazonBrowserClient(Protocol):
    async def __aenter__(self) -> AmazonBrowserClient: ...

    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    async def verify_ip_location(self) -> ProxyLocation: ...

    async def set_delivery_location(self, postal_code: str) -> str | None: ...

    async def search(
        self,
        *,
        keyword: str,
        marketplace: str,
        search_depth: int,
    ) -> SerpResult: ...
