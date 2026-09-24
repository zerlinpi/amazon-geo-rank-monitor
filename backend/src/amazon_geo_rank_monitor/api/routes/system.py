from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _age_seconds(value: datetime | None, *, now: datetime) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max((now - value.astimezone(UTC)).total_seconds(), 0.0)


def _label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@router.get("/workers")
def list_workers(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
):
    del owner_id
    repository = get_services(request).worker_status_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="worker status is unavailable")
    return repository.list()


@router.get("/queue")
def queue_summary(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
):
    del owner_id
    return get_services(request).job_repository.queue_summary()


@router.get("/dead-letters")
def list_dead_letters(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
    limit: int = 50,
):
    del owner_id
    return get_services(request).job_repository.list_dead_letters(limit=limit)


@router.post("/dead-letters/{job_id}/requeue")
def requeue_dead_letter(
    job_id: str,
    request: Request,
    owner_id: str = Depends(require_scope("system:write")),
):
    del owner_id
    try:
        return get_services(request).job_repository.requeue_dead_letter(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/audit")
def list_audit_events(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
    limit: int = 100,
    api_key_id: str | None = None,
):
    repository = get_services(request).audit_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="audit log is unavailable")
    return repository.list(
        owner_id=owner_id,
        limit=limit,
        api_key_id=api_key_id,
    )


@router.get("/metrics")
def prometheus_metrics(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
):
    del owner_id
    services = get_services(request)
    summary = services.job_repository.queue_summary()
    workers = (
        services.worker_status_repository.list()
        if services.worker_status_repository is not None
        else []
    )
    now = datetime.now(UTC)
    lines = [
        "# HELP agrm_rank_jobs Current rank jobs by state.",
        "# TYPE agrm_rank_jobs gauge",
    ]
    for job_status, count in sorted(summary["counts"].items()):
        lines.append(
            f'agrm_rank_jobs{{status="{_label(job_status)}"}} {int(count)}'
        )

    oldest = summary["oldest_pending_at"]
    lines.extend(
        [
            "# HELP agrm_queue_oldest_pending_age_seconds Age of the oldest pending job.",
            "# TYPE agrm_queue_oldest_pending_age_seconds gauge",
            (
                "agrm_queue_oldest_pending_age_seconds "
                f"{_age_seconds(oldest, now=now):.3f}"
            ),
            "# HELP agrm_service_heartbeat_age_seconds Age of the latest service heartbeat.",
            "# TYPE agrm_service_heartbeat_age_seconds gauge",
            "# HELP agrm_service_processed_jobs_total Jobs dispatched or processed by service.",
            "# TYPE agrm_service_processed_jobs_total counter",
        ]
    )
    for worker in workers:
        labels = (
            f'worker_id="{_label(worker["worker_id"])}",'
            f'worker_type="{_label(worker["worker_type"])}",'
            f'status="{_label(worker["status"])}"'
        )
        lines.append(
            "agrm_service_heartbeat_age_seconds"
            f"{{{labels}}} {_age_seconds(worker['last_seen_at'], now=now):.3f}"
        )
        lines.append(
            "agrm_service_processed_jobs_total"
            f"{{{labels}}} {int(worker['processed_jobs'])}"
        )

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
