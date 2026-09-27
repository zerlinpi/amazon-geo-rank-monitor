from datetime import UTC, datetime

from amazon_geo_rank_monitor.verification.budget import forecast_daily_budget


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
