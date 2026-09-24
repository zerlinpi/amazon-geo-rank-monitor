from __future__ import annotations

from amazon_geo_rank_monitor.billing.rate_card import RateCard


class RankUsageMeter:
    def __init__(self, *, billing_repository, rate_card: RateCard) -> None:
        self._billing = billing_repository
        self._rate_card = rate_card

    def reserve_rank_job(
        self,
        *,
        job_id: str,
        owner_id: str,
        provider_mode: str,
        probe_count: int,
    ) -> dict:
        if probe_count <= 0:
            raise ValueError("probe_count must be positive")
        amount = probe_count * self._rate_card.credits_per_probe(provider_mode)
        return self._billing.reserve(
            owner_id=owner_id,
            amount=amount,
            idempotency_key=f"rank-job:{job_id}",
            reference_type="rank_job",
            reference_id=job_id,
        )

    def settle_rank_job(
        self,
        *,
        reservation: dict,
        job_id: str,
        provider_mode: str,
        successful_probe_count: int,
    ) -> dict:
        if successful_probe_count < 0:
            raise ValueError("successful_probe_count cannot be negative")
        actual_amount = (
            successful_probe_count
            * self._rate_card.credits_per_probe(provider_mode)
        )
        return self._billing.settle(
            reservation["id"],
            actual_amount=actual_amount,
            idempotency_key=f"rank-job:{job_id}",
        )

    def release_rank_job(
        self,
        *,
        reservation: dict,
        job_id: str,
    ) -> dict:
        return self._billing.release(
            reservation["id"],
            idempotency_key=f"rank-job-error:{job_id}",
        )
