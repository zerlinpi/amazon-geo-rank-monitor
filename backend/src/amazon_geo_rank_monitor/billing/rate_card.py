from dataclasses import dataclass


@dataclass(frozen=True)
class RateCard:
    managed_serp_credits: int = 1
    strict_serp_credits: int = 5

    def __post_init__(self) -> None:
        if self.managed_serp_credits <= 0 or self.strict_serp_credits <= 0:
            raise ValueError("SERP credit rates must be positive")

    def credits_per_probe(self, provider_mode: str) -> int:
        if provider_mode == "managed":
            return self.managed_serp_credits
        if provider_mode == "strict":
            return self.strict_serp_credits
        raise ValueError(f"unsupported provider mode: {provider_mode}")
