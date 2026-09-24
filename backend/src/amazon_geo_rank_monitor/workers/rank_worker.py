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
        worker_status_repository=None,
        worker_id: str = "rank-worker",
    ) -> None:
        self._jobs = job_repository
        self._rank_repository = rank_repository
        self._providers = provider_registry
        self._billing = billing_repository
        self._rate_card = rate_card or RateCard()
        self._worker_status = worker_status_repository
        self._worker_id = worker_id

    def _heartbeat(
        self,
        *,
        status: str,
        last_job_id: str | None = None,
        last_error: str | None = None,
        processed_delta: int = 0,
    ) -> None:
        if self._worker_status is None:
            return
        self._worker_status.heartbeat(
            worker_id=self._worker_id,
            status=status,
            last_job_id=last_job_id,
            last_error=last_error,
            processed_delta=processed_delta,
        )

    async def run_once(self) -> dict | None:
        self._heartbeat(status="idle")
        job = self._jobs.claim_one()
        if job is None:
            return None
        self._heartbeat(status="running", last_job_id=job["id"])

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
            failed = self._jobs.fail(job["id"], error=str(exc))
            self._heartbeat(
                status="error",
                last_job_id=job["id"],
                last_error=str(exc),
                processed_delta=1,
            )
            return failed
        completed = self._jobs.complete(
            job["id"],
            run_id=result.run_id,
            status=result.status,
        )
        self._heartbeat(
            status="idle",
            last_job_id=job["id"],
            processed_delta=1,
        )
        return completed
