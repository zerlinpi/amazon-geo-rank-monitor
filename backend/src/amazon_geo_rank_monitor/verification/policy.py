from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from amazon_geo_rank_monitor.domain.models import GeoProfile, RankObservation


@dataclass(frozen=True)
class AutoStrictVerificationPolicy:
    enabled: bool = False
    rank_delta_threshold: int = 20
    verify_not_found_after_found: bool = True
    verify_geo_mismatch: bool = True
    recover_low_confidence: bool = True
    min_confidence: Decimal = Decimal("0.75")

    def __post_init__(self) -> None:
        if self.rank_delta_threshold < 1:
            raise ValueError("rank_delta_threshold must be at least 1")
        if self.min_confidence <= 0 or self.min_confidence > 1:
            raise ValueError("min_confidence must be greater than 0 and at most 1")

    def evaluate(
        self,
        *,
        managed_observations: list[RankObservation],
        previous_observations: list[RankObservation],
        geo_profile: GeoProfile,
        geo_metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        if not self.enabled:
            return []

        reasons: list[str] = []
        previous_by_asin = {
            observation.asin: observation for observation in previous_observations
        }

        for current in managed_observations:
            previous = previous_by_asin.get(current.asin)
            if previous is None:
                continue
            if (
                self.verify_not_found_after_found
                and previous.found
                and not current.found
            ):
                reasons.append(f"not_found_after_found:{current.asin}")
                continue
            if previous.found and current.found:
                delta = abs(current.effective_rank - previous.effective_rank)
                if delta >= self.rank_delta_threshold:
                    reasons.append(
                        f"rank_movement:{current.asin}:{delta}"
                    )

        if self.verify_geo_mismatch:
            metadata = geo_metadata or {}
            observed_country = self._text(metadata.get("observed_ip_country"))
            if (
                observed_country
                and observed_country.casefold() != geo_profile.ip_country.casefold()
            ):
                reasons.append("geo_country_mismatch")

            observed_postal = self._text(metadata.get("observed_ip_postal_code"))
            if (
                geo_profile.ip_postal_code
                and observed_postal
                and observed_postal.casefold()
                != geo_profile.ip_postal_code.casefold()
            ):
                reasons.append("geo_postal_mismatch")

            confirmed_delivery = self._text(
                metadata.get("confirmed_delivery_postal_code")
            )
            if (
                confirmed_delivery
                and confirmed_delivery.casefold()
                != geo_profile.delivery_postal_code.casefold()
            ):
                reasons.append("delivery_postal_mismatch")

        return list(dict.fromkeys(reasons))

    def low_confidence_trigger(
        self,
        *,
        successful_weight: Decimal,
        total_weight: Decimal,
    ) -> str | None:
        if not self.enabled or not self.recover_low_confidence:
            return None
        if total_weight <= 0:
            return None
        confidence = successful_weight / total_weight
        if confidence >= self.min_confidence:
            return None
        return f"low_confidence:{confidence.quantize(Decimal('0.01'))}"

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
