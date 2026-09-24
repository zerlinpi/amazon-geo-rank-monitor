from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateCard:
    managed_serp: int = 1
    browser_verified_serp: int = 5

    def per_probe(self, provider_mode: str) -> int:
        if provider_mode == "managed":
            return self.managed_serp
        if provider_mode == "strict":
            return self.browser_verified_serp
        raise ValueError("provider_mode must be managed or strict")

    def quote(self, provider_mode: str, probe_count: int) -> int:
        if probe_count < 0:
            raise ValueError("probe_count must be non-negative")
        return self.per_probe(provider_mode) * probe_count
