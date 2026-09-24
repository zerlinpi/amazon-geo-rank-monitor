from __future__ import annotations

from amazon_geo_rank_monitor.domain.models import RankCheckRequest
from amazon_geo_rank_monitor.monitor.service import RankMonitorService


class RankWorker:
    def __init__(self, *, job_repository, rank_repository, provider_registry) -> None:
        self._jobs = job_repository
        self._rank_repository = rank_repository
        self._providers = provider_registry

    async def run_once(self) -> dict | None:
        job = self._jobs.claim_one()
        if job is None:
            return None
        try:
            request = RankCheckRequest.model_validate(job["request_payload"])
            provider = self._providers.get(job["provider_mode"])
            service = RankMonitorService(
                provider=provider,
                repository=self._rank_repository,
            )
            result = await service.check_with_result(
                request,
                owner_id=job["owner_id"],
            )
        except Exception as exc:
            return self._jobs.fail(job["id"], error=str(exc))
        return self._jobs.complete(job["id"], run_id=result.run_id)
