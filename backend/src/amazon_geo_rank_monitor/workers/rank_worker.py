from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from amazon_geo_rank_monitor.billing.rate_card import RateCard
from amazon_geo_rank_monitor.domain.models import RankCheckRequest
from amazon_geo_rank_monitor.monitor.service import RankMonitorService

logger = logging.getLogger("amazon_geo_rank_monitor.worker")


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
        alert_service=None,
        probe_cache=None,
        auto_strict_verifier=None,
        worker_id: str = "rank-worker",
        lease_seconds: float = 900.0,
        retry_base_seconds: float = 30.0,
        retry_max_seconds: float = 900.0,
    ) -> None:
        self._jobs = job_repository
        self._rank_repository = rank_repository
        self._providers = provider_registry
        self._billing = billing_repository
        self._rate_card = rate_card or RateCard()
        self._worker_status = worker_status_repository
        self._alerts = alert_service
        self._probe_cache = probe_cache
        self._auto_strict_verifier = auto_strict_verifier
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds

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

    async def _renew_lease(self, job_id: str) -> None:
        interval = max(min(self._lease_seconds / 3, 30.0), 1.0)
        while True:
            await asyncio.sleep(interval)
            renewed = self._jobs.renew_lease(
                job_id,
                worker_id=self._worker_id,
                lease_seconds=self._lease_seconds,
            )
            if not renewed:
                return

    async def run_once(self) -> dict | None:
        recovery = self._jobs.recover_stale()
        if self._billing is not None:
            for attempt in recovery["recovered_attempts"]:
                self._billing.release_by_idempotency_key(
                    "rank_job:"
                    f"{attempt['job_id']}:attempt:{attempt['attempt_count']}"
                )
        if recovery["dead_lettered"]:
            self._heartbeat(
                status="warning",
                last_error=(
                    f"recovered stale jobs: {recovery['retried']} retried, "
                    f"{recovery['dead_lettered']} dead-lettered"
                ),
            )
        else:
            self._heartbeat(status="idle")

        job = self._jobs.claim_one(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if job is None:
            return None
        self._heartbeat(status="running", last_job_id=job["id"])
        lease_task = asyncio.create_task(self._renew_lease(job["id"]))

        reservation = None
        try:
            request_payload = dict(job["request_payload"])
            verification_policy = request_payload.pop(
                "_verification_policy",
                None,
            )
            request = RankCheckRequest.model_validate(request_payload)
            provider = self._providers.get(job["provider_mode"])
            prepared_cache = {}
            if self._probe_cache is not None:
                try:
                    prepared_cache = self._probe_cache.prefetch(
                        owner_id=job["owner_id"],
                        provider_mode=job["provider_mode"],
                        provider=provider,
                        request=request,
                    )
                except Exception:
                    logger.exception(
                        "probe_cache_prefetch_failed owner_id=%s job_id=%s",
                        job["owner_id"],
                        job["id"],
                    )
            reserve_probe_count = max(
                len(request.geo_profiles) - len(prepared_cache),
                0,
            )
            if self._billing is not None and reserve_probe_count > 0:
                reservation = self._billing.reserve(
                    owner_id=job["owner_id"],
                    credits=self._rate_card.quote(
                        job["provider_mode"], reserve_probe_count
                    ),
                    idempotency_key=(
                        f"rank_job:{job['id']}:attempt:{job['attempt_count']}"
                    ),
                    reference_type="rank_job",
                    reference_id=job["id"],
                )

            strict_verifier = self._auto_strict_verifier
            if (
                strict_verifier is not None
                and isinstance(verification_policy, dict)
            ):
                strict_verifier = strict_verifier.for_monitor(
                    enabled=verification_policy.get("enabled"),
                    min_confidence=verification_policy.get("min_confidence"),
                    max_upstream_probes_per_run=verification_policy.get(
                        "max_upstream_probes_per_run"
                    ),
                )
            service = RankMonitorService(
                provider=provider,
                repository=self._rank_repository,
                probe_cache=self._probe_cache,
                provider_mode=job["provider_mode"],
                strict_verifier=strict_verifier,
            )
            result = await service.check_with_result(
                request,
                owner_id=job["owner_id"],
                prepared_cache=prepared_cache,
                verification_reference_id=f"job:{job['id']}",
            )

            if reservation is not None:
                self._billing.settle(
                    reservation["id"],
                    credits_used=self._rate_card.quote(
                        job["provider_mode"],
                        result.primary_upstream_probe_count,
                    ),
                )

            if result.status == "failed":
                message = "; ".join(str(item) for item in result.errors)
                outcome = self._jobs.retry_or_dead_letter(
                    job["id"],
                    error=message or "rank execution failed",
                    base_delay_seconds=self._retry_base_seconds,
                    max_delay_seconds=self._retry_max_seconds,
                )
                self._heartbeat(
                    status=(
                        "dead_letter"
                        if outcome["status"] == "dead_letter"
                        else "retry_wait"
                    ),
                    last_job_id=job["id"],
                    last_error=message or "rank execution failed",
                    processed_delta=1,
                )
                return outcome
        except Exception as exc:
            if reservation is not None:
                self._billing.release(reservation["id"])
            outcome = self._jobs.retry_or_dead_letter(
                job["id"],
                error=str(exc),
                base_delay_seconds=self._retry_base_seconds,
                max_delay_seconds=self._retry_max_seconds,
            )
            self._heartbeat(
                status=(
                    "dead_letter"
                    if outcome["status"] == "dead_letter"
                    else "retry_wait"
                ),
                last_job_id=job["id"],
                last_error=str(exc),
                processed_delta=1,
            )
            return outcome
        finally:
            lease_task.cancel()
            with suppress(asyncio.CancelledError):
                await lease_task

        completed = self._jobs.complete(
            job["id"],
            run_id=result.run_id,
            status=result.status,
        )
        if (
            self._alerts is not None
            and job.get("monitor_target_id")
            and result.status in {"succeeded", "partially_succeeded"}
        ):
            try:
                self._alerts.evaluate_run(
                    owner_id=job["owner_id"],
                    monitor_target_id=job["monitor_target_id"],
                    run_id=result.run_id,
                )
            except Exception:
                # Notification failures must never roll a completed rank job back.
                pass
        self._heartbeat(
            status="idle",
            last_job_id=job["id"],
            processed_delta=1,
        )
        return completed
