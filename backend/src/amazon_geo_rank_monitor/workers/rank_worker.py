from __future__ import annotations

from amazon_geo_rank_monitor.billing.errors import InsufficientCreditsError
from amazon_geo_rank_monitor.domain.models import RankCheckRequest
from amazon_geo_rank_monitor.monitor.service import RankMonitorService


class RankWorker:
    def __init__(
        self,
        *,
        job_repository,
        rank_repository,
        provider_registry,
        usage_meter=None,
    ) -> None:
        self._jobs = job_repository
        self._rank_repository = rank_repository
        self._providers = provider_registry
        self._usage_meter = usage_meter

    async def run_once(self) -> dict | None:
        job = self._jobs.claim_one()
        if job is None:
            return None

        reservation = None
        try:
            request = RankCheckRequest.model_validate(job["request_payload"])
            if self._usage_meter is not None:
                reservation = self._usage_meter.reserve_rank_job(
                    job_id=job["id"],
                    owner_id=job["owner_id"],
                    provider_mode=job["provider_mode"],
                    probe_count=len(request.geo_profiles),
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

            if self._usage_meter is not None and reservation is not None:
                run = self._rank_repository.get_run(
                    result.run_id,
                    owner_id=job["owner_id"],
                )
                self._usage_meter.settle_rank_job(
                    reservation=reservation,
                    job_id=job["id"],
                    provider_mode=job["provider_mode"],
                    successful_probe_count=run["settled_probe_count"],
                )
        except InsufficientCreditsError as exc:
            return self._jobs.fail(
                job["id"],
                error=f"INSUFFICIENT_CREDITS: {exc}",
            )
        except Exception as exc:
            if self._usage_meter is not None and reservation is not None:
                self._usage_meter.release_rank_job(
                    reservation=reservation,
                    job_id=job["id"],
                )
            return self._jobs.fail(job["id"], error=str(exc))
        return self._jobs.complete(job["id"], run_id=result.run_id)
