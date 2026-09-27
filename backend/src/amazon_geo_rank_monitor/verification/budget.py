from __future__ import annotations

from datetime import UTC, datetime, timedelta

REFERENCE_TYPE = "auto_strict_verification"
FORECAST_MIN_SAMPLE_SECONDS = 3600


def forecast_daily_budget(
    status: dict,
    *,
    now: datetime,
    window_start: datetime,
    reset_at: datetime,
    min_sample_seconds: int = FORECAST_MIN_SAMPLE_SECONDS,
) -> dict:
    """Project end-of-day Strict Verification credit demand from today's pace."""

    unavailable = {
        "available": False,
        "sample_seconds": max(
            int((now - window_start).total_seconds()),
            0,
        ),
        "burn_rate_credits_per_hour": None,
        "projected_committed_credits": None,
        "projected_utilization_pct": None,
        "estimated_exhaustion_at": None,
        "runway_minutes": None,
    }
    if not status.get("billing_available", True):
        return unavailable

    limit = status.get("limit")
    committed = int(status.get("committed_credits") or 0)
    elapsed_seconds = max((now - window_start).total_seconds(), 0.0)
    if (
        limit is None
        or int(limit) <= 0
        or committed <= 0
        or elapsed_seconds < min_sample_seconds
    ):
        return unavailable

    elapsed_hours = elapsed_seconds / 3600
    burn_rate = committed / elapsed_hours
    day_hours = (reset_at - window_start).total_seconds() / 3600
    projected_committed = burn_rate * day_hours
    projected_utilization = (projected_committed / int(limit)) * 100

    estimated_exhaustion_at = None
    runway_minutes = None
    if projected_committed >= int(limit):
        exhaustion = window_start + timedelta(
            hours=int(limit) / burn_rate,
        )
        if exhaustion <= reset_at:
            if exhaustion < now and committed >= int(limit):
                exhaustion = now
            estimated_exhaustion_at = exhaustion.isoformat()
            runway_minutes = max(
                round((exhaustion - now).total_seconds() / 60),
                0,
            )

    return {
        "available": True,
        "sample_seconds": int(elapsed_seconds),
        "burn_rate_credits_per_hour": round(burn_rate, 2),
        "projected_committed_credits": round(projected_committed, 2),
        "projected_utilization_pct": round(projected_utilization, 2),
        "estimated_exhaustion_at": estimated_exhaustion_at,
        "runway_minutes": runway_minutes,
    }


def build_daily_budget_status(
    *,
    billing_repository,
    owner_id: str,
    limit: int | None,
    now: datetime | None = None,
) -> dict:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)
    window_start = current.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    reset_at = window_start + timedelta(days=1)

    if (
        billing_repository is not None
        and hasattr(billing_repository, "reference_budget_status")
    ):
        status = {
            "billing_available": True,
            **billing_repository.reference_budget_status(
                owner_id=owner_id,
                reference_type=REFERENCE_TYPE,
                since=window_start,
                until=current,
                limit=limit,
            ),
        }
    else:
        status = {
            "billing_available": False,
            "limit": limit,
            "settled_credits": 0,
            "reserved_credits": 0,
            "committed_credits": 0,
            "remaining_credits": limit if limit is not None else None,
            "utilization_pct": 0.0,
        }

    status.update(
        {
            "window_start": window_start.isoformat(),
            "reset_at": reset_at.isoformat(),
        }
    )
    status["forecast"] = forecast_daily_budget(
        status,
        now=current,
        window_start=window_start,
        reset_at=reset_at,
    )
    return status
