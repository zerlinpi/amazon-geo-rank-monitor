from __future__ import annotations

from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.domain.models import RankCheckRequest
from amazon_geo_rank_monitor.monitor.service import RankMonitorService


class RankWorker:
    def __init__(
        self,
        *,
        job_repository,
        rank_repository,
        provider_registry,
        billing_repository=None,
        rate_card: RateCard | None = None,
    ) -> None:
        self._jobs = job_repository
        self._rank_repository = rank_repository
        self._providers = provider_registry
        self._billing = billing_repository
        self._rate_card = rate_card or RateCard()

    async def run_once(self) -> dict | None:
        job = self._jobs.claim_one()
        if job is None:
            return None

        reservation = None
        try:
            request = RankCheckRequest.model_validate(job["request_payload"])
            if self._billing is not None:
                reservation = self._billing.reserve(
                    owner_id=job["owner_id"],
                    credits=self._rate_card.quote(
                        job["provider_mode"], len(request.geo_profiles)
                    ),
                    idempotency_key=f"rank_job:{job['id']}",
                    reference_type="rank_job",
                    reference_id=job["id"],
                )

            provider = self._providers.get(job["provider_mode"])
            service = RankMonitorService(
                provider=provider,
                repository=self._rank_repository,
            )
            result = await service.check_with_result(
                request,
                owner_id=job["owner_id"],
            )

            if reservation is not None:
                successful_geos = len(
                    {item.geo_profile_id for item in result.observations}
                )
                self._billing.settle(
                    reservation["id"],
                    credits_used=self._rate_card.quote(
                        job["provider_mode"], successful_geos
                    ),
                )
        except Exception as exc:
            if reservation is not None:
                self._billing.release(reservation["id"])
            return self._jobs.fail(job["id"], error=str(exc))
        return self._jobs.complete(job["id"], run_id=result.run_id)
