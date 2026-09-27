from datetime import UTC, datetime

from amazon_geo_rank_monitor.verification.budget import (
    evaluate_daily_budget_pacing,
    forecast_daily_budget,
)


def status(*, limit: int | None, committed: int, billing_available: bool = True):
    return {
        "billing_available": billing_available,
        "limit": limit,
        "committed_credits": committed,
    }


def test_forecast_projects_end_of_day_without_exhaustion() -> None:
    window_start = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    reset_at = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)

    forecast = forecast_daily_budget(
        status(limit=100, committed=40),
        now=now,
        window_start=window_start,
        reset_at=reset_at,
    )

    assert forecast == {
        "available": True,
        "sample_seconds": 43200,
        "burn_rate_credits_per_hour": 3.33,
        "projected_committed_credits": 80.0,
        "projected_utilization_pct": 80.0,
        "estimated_exhaustion_at": None,
        "runway_minutes": None,
    }


def test_forecast_estimates_exhaustion_time_and_runway() -> None:
    window_start = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    reset_at = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)

    forecast = forecast_daily_budget(
        status(limit=100, committed=60),
        now=now,
        window_start=window_start,
        reset_at=reset_at,
    )

    assert forecast["available"] is True
    assert forecast["burn_rate_credits_per_hour"] == 5.0
    assert forecast["projected_committed_credits"] == 120.0
    assert forecast["projected_utilization_pct"] == 120.0
    assert forecast["estimated_exhaustion_at"] == "2026-09-27T20:00:00+00:00"
    assert forecast["runway_minutes"] == 480


def test_forecast_requires_stable_sample_finite_budget_and_spend() -> None:
    window_start = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    reset_at = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)

    too_early = forecast_daily_budget(
        status(limit=100, committed=5),
        now=datetime(2026, 9, 27, 0, 30, tzinfo=UTC),
        window_start=window_start,
        reset_at=reset_at,
    )
    unlimited = forecast_daily_budget(
        status(limit=None, committed=50),
        now=datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
        window_start=window_start,
        reset_at=reset_at,
    )
    no_spend = forecast_daily_budget(
        status(limit=100, committed=0),
        now=datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
        window_start=window_start,
        reset_at=reset_at,
    )

    assert too_early["available"] is False
    assert unlimited["available"] is False
    assert no_spend["available"] is False


def test_forecast_is_unavailable_when_billing_is_unavailable() -> None:
    window_start = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    reset_at = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
    forecast = forecast_daily_budget(
        status(limit=100, committed=50, billing_available=False),
        now=datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
        window_start=window_start,
        reset_at=reset_at,
    )
    assert forecast["available"] is False



def test_pacing_defers_next_probe_when_forecast_would_exhaust_cap() -> None:
    window_start = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    reset_at = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
    pacing = evaluate_daily_budget_pacing(
        {
            "billing_available": True,
            "limit": 100,
            "committed_credits": 60,
            "forecast": {
                "available": True,
                "estimated_exhaustion_at": "2026-09-27T20:00:00+00:00",
            },
        },
        now=now,
        window_start=window_start,
        reset_at=reset_at,
        enabled=True,
        next_probe_credits=5,
    )

    assert pacing["active"] is True
    assert pacing["allowance_credits"] == 50
    assert pacing["defer_next_probe"] is True
    assert pacing["reason"] == "paced_allowance_exceeded"
    assert pacing["resume_at"] == "2026-09-27T15:36:00+00:00"


def test_pacing_allows_probe_that_fits_current_linear_allowance() -> None:
    window_start = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    reset_at = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
    pacing = evaluate_daily_budget_pacing(
        {
            "billing_available": True,
            "limit": 100,
            "committed_credits": 45,
            "forecast": {
                "available": True,
                "estimated_exhaustion_at": "2026-09-27T23:00:00+00:00",
            },
        },
        now=now,
        window_start=window_start,
        reset_at=reset_at,
        enabled=True,
        next_probe_credits=5,
    )

    assert pacing["active"] is True
    assert pacing["allowance_credits"] == 50
    assert pacing["defer_next_probe"] is False
    assert pacing["reason"] == "within_paced_allowance"


def test_pacing_is_inactive_without_projected_exhaustion() -> None:
    window_start = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    reset_at = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
    pacing = evaluate_daily_budget_pacing(
        {
            "billing_available": True,
            "limit": 100,
            "committed_credits": 40,
            "forecast": {
                "available": True,
                "estimated_exhaustion_at": None,
            },
        },
        now=now,
        window_start=window_start,
        reset_at=reset_at,
        enabled=True,
        next_probe_credits=5,
    )

    assert pacing["active"] is False
    assert pacing["defer_next_probe"] is False
    assert pacing["reason"] == "forecast_not_exhausting"



def test_pacing_yields_to_hard_cap_when_next_probe_would_exceed_limit() -> None:
    window_start = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)
    now = datetime(2026, 9, 27, 23, 0, tzinfo=UTC)
    reset_at = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
    pacing = evaluate_daily_budget_pacing(
        {
            "billing_available": True,
            "limit": 100,
            "committed_credits": 98,
            "forecast": {
                "available": True,
                "estimated_exhaustion_at": "2026-09-27T23:30:00+00:00",
            },
        },
        now=now,
        window_start=window_start,
        reset_at=reset_at,
        enabled=True,
        next_probe_credits=5,
    )

    assert pacing["active"] is True
    assert pacing["defer_next_probe"] is False
    assert pacing["reason"] == "hard_cap_authoritative"
