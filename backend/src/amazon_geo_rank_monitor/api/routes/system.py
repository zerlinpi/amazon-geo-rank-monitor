from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from amazon_geo_rank_monitor.api.dependencies import get_services, require_scope
from amazon_geo_rank_monitor.billing.rate_card import RateCard

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
    repository = get_services(request).worker_status_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="worker status is unavailable")
    return [{**item, "last_job_id": None, "last_error": None} for item in repository.list()]


@router.get("/queue")
def queue_summary(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
):
    return get_services(request).job_repository.queue_summary(owner_id=owner_id)


@router.get("/dead-letters")
def list_dead_letters(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
    limit: int = 50,
):
    return get_services(request).job_repository.list_dead_letters(limit=limit, owner_id=owner_id)


@router.post("/dead-letters/{job_id}/requeue")
def requeue_dead_letter(
    job_id: str,
    request: Request,
    owner_id: str = Depends(require_scope("system:write")),
):
    try:
        return get_services(request).job_repository.requeue_dead_letter(job_id, owner_id=owner_id)
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


@router.get("/verification-summary")
def verification_summary(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
):
    repository = get_services(request).rank_repository
    if repository is None or not hasattr(repository, "verification_summary"):
        raise HTTPException(
            status_code=503,
            detail="verification summary is unavailable",
        )
    return repository.verification_summary(owner_id=owner_id)


@router.get("/verification-analytics")
def verification_analytics(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
    hours: int = Query(default=168, ge=1, le=2160),
):
    services = get_services(request)
    repository = services.rank_repository
    if repository is None or not hasattr(repository, "verification_analytics"):
        raise HTTPException(
            status_code=503,
            detail="verification analytics is unavailable",
        )

    until = datetime.now(UTC)
    since = until - timedelta(hours=hours)
    analytics = repository.verification_analytics(
        owner_id=owner_id,
        since=since,
        until=until,
    )

    rate_card = services.rate_card or RateCard()
    strict_credit_rate = rate_card.per_probe("strict")
    billing = services.billing_repository
    billing_available = (
        billing is not None
        and hasattr(billing, "reference_credit_usage")
    )
    usage = (
        billing.reference_credit_usage(
            owner_id=owner_id,
            reference_type="auto_strict_verification",
            since=since,
            until=until,
        )
        if billing_available
        else {
            "settlement_count": 0,
            "credits_spent": 0,
            "daily": [],
        }
    )

    daily = {
        item["date"]: {**item, "credits_spent": 0}
        for item in analytics.pop("daily")
    }
    for item in usage["daily"]:
        point = daily.setdefault(
            item["date"],
            {
                "date": item["date"],
                "requested": 0,
                "attempted": 0,
                "succeeded": 0,
                "skipped": 0,
                "manual_requested": 0,
                "cache_hits": 0,
                "recovered_failed_geos": 0,
                "credits_spent": 0,
            },
        )
        point["credits_spent"] += item["credits_spent"]

    requested = analytics["strict_requested"]
    succeeded = analytics["strict_succeeded"]
    skipped = analytics["strict_skipped"]
    credits_spent = usage["credits_spent"]
    return {
        "window": {
            "hours": hours,
            "since": since,
            "until": until,
        },
        **analytics,
        "success_rate_pct": (
            round((succeeded / requested) * 100, 2)
            if requested
            else 0.0
        ),
        "skip_rate_pct": (
            round((skipped / requested) * 100, 2)
            if requested
            else 0.0
        ),
        "billing_available": billing_available,
        "strict_credit_rate": strict_credit_rate,
        "billed_strict_probes": usage["settlement_count"],
        "credits_spent": credits_spent if billing_available else None,
        "credits_per_success": (
            round(credits_spent / succeeded, 2)
            if billing_available and succeeded
            else None
        ),
        "estimated_cache_savings_credits": (
            analytics["cache_hits"] * strict_credit_rate
        ),
        "daily": [daily[key] for key in sorted(daily)],
    }


@router.get("/metrics")
def prometheus_metrics(
    request: Request,
    owner_id: str = Depends(require_scope("system:read")),
):
    services = get_services(request)
    summary = services.job_repository.queue_summary(owner_id=owner_id)
    workers = (
        services.worker_status_repository.list()
        if services.worker_status_repository is not None
        else []
    )
    now = datetime.now(UTC)
    verification = (
        services.rank_repository.verification_summary(owner_id=owner_id)
        if services.rank_repository is not None
        and hasattr(services.rank_repository, "verification_summary")
        else {}
    )
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

    if verification:
        lines.extend(
            [
                "# HELP agrm_auto_strict_verification_total "
                "Automatic strict verification outcomes.",
                "# TYPE agrm_auto_strict_verification_total counter",
            ]
        )
        for outcome, count in sorted(verification.items()):
            normalized = outcome.removeprefix("strict_")
            lines.append(
                "agrm_auto_strict_verification_total"
                f'{{outcome="{_label(normalized)}"}} {int(count)}'
            )

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
