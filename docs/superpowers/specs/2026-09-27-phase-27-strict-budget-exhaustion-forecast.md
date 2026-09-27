# Phase 27 — Strict Daily Budget Exhaustion Forecast

## Goal

Turn the live UTC-day Strict Verification budget state into a directional
forecast so operators can act before the hard daily cap is reached.

The forecast answers:

- what is the current committed-credit burn rate;
- how many Strict Verification credits the current pace implies by UTC day end;
- what percentage of the configured cap that projection represents;
- whether the current pace is expected to exhaust the cap today;
- if so, the estimated exhaustion time and remaining runway.

## Shared source of truth

Phase 27 centralizes daily budget status construction in the verification
budget helper. The same helper is used by:

- Workspace verification policy responses;
- completed rank-run verification metadata.

This keeps Team settings, System Status, alert evaluation, and Run History on
the same settled + reserved credit semantics used by the Phase 24 hard
guardrail.

## Forecast model

The model intentionally uses a simple transparent intraday pace projection.

For the current UTC day:

```text
committed = settled + reserved
elapsed_hours = now - UTC midnight
burn_rate = committed / elapsed_hours
projected_EOD = burn_rate * 24
projected_utilization = projected_EOD / daily_limit * 100
```

If projected EOD demand reaches or exceeds the configured cap:

```text
estimated_exhaustion = UTC midnight + daily_limit / burn_rate
```

The forecast is directional, not a billing guarantee. Rank schedules,
verification triggers, cache hits, operator actions, and demand can change
later in the day.

## Stability rules

A forecast is available only when all of the following are true:

- billing status is available;
- the Workspace has a finite positive daily Strict Verification credit cap;
- at least one Strict Verification credit is committed;
- at least one hour has elapsed since UTC midnight.

The one-hour minimum prevents a few early-morning probes from creating an
extreme full-day extrapolation.

Unlimited budgets, zero-credit caps, no-spend days, missing billing state, and
the first hour of the UTC day return `forecast.available=false`.

## API shape

`daily_budget_status` now includes:

```json
{
  "forecast": {
    "available": true,
    "sample_seconds": 43200,
    "burn_rate_credits_per_hour": 5.0,
    "projected_committed_credits": 120.0,
    "projected_utilization_pct": 120.0,
    "estimated_exhaustion_at": "2026-09-27T20:00:00+00:00",
    "runway_minutes": 480
  }
}
```

Projected utilization is deliberately not capped at 100%, so operators can see
the size of projected demand beyond the hard cap.

## UI

### Team

The live Strict Verification budget card adds:

- current burn rate;
- projected UTC end-of-day committed credits;
- projected cap utilization;
- estimated exhaustion time when the cap is projected to be reached.

### System Status

The same forecast appears beside the existing live guardrail and refreshes in
the existing 10-second operations refresh loop.

### Run History

Because completed runs already snapshot `daily_budget_status`, the forecast
that existed when a run completed is retained as immutable audit evidence.

Run History shows the completion-time burn rate, EOD projection, and estimated
exhaustion time.

## Safety boundaries

- Forecasting never reserves, releases, or spends credits.
- The Phase 24 hard guardrail remains authoritative.
- Forecast values never bypass the runtime kill switch or any probe budget.
- The forecast does not automatically change Workspace policy.
- A forecast can become stale as later-day demand changes; live Team/System
  views should be used for current operational decisions.

## Persistence and migration

No schema migration is required.

Live status is computed from existing credit reservations. Run-level forecast
evidence is stored inside the existing JSON verification metadata.
