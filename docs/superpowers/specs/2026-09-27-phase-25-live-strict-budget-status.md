# Phase 25 — Live Strict Verification Budget Status

## Goal

Make the Phase 24 daily Strict Verification guardrail observable before it
blocks new paid probes.

Workspace operators need to see, for the current UTC day:

- credits already settled;
- credits currently reserved by in-flight strict verification;
- total committed credits;
- remaining credits under the configured cap;
- current utilization percentage;
- the next UTC reset time.

## Source of truth

The live status deliberately uses the same `credit_reservations` semantics as
the Phase 24 enforcement path.

For billing reference type:

```text
auto_strict_verification
```

the current UTC-day status is:

```text
settled = sum(settled_amount where status=settled)
reserved = sum(amount where status=reserved)
committed = settled + reserved
remaining = max(limit - committed, 0)
```

Released reservations are excluded.

This is different from Phase 23 historical cost analytics, which use immutable
`credit_ledger_entries` settlement rows and answer "what did we actually
spend?". Phase 25 answers "how much of today's hard guardrail is already
committed right now?".

## Workspace policy API

`GET /api/v1/team/verification-policy` now includes:

```json
{
  "daily_budget_status": {
    "billing_available": true,
    "window_start": "2026-09-27T00:00:00+00:00",
    "reset_at": "2026-09-28T00:00:00+00:00",
    "limit": 100,
    "settled_credits": 25,
    "reserved_credits": 5,
    "committed_credits": 30,
    "remaining_credits": 70,
    "utilization_pct": 30.0
  }
}
```

When the Workspace cap is unlimited, `limit` and `remaining_credits` are
`null`, while settled/reserved/committed credits still remain observable.

When billing status is unavailable the API reports
`billing_available=false` and preserves the configured limit.

## UI

### Team settings

**Workspace → Team → Automatic strict verification** shows a live budget panel
next to the daily guardrail controls.

The panel displays:

- settled;
- reserved;
- committed;
- remaining;
- utilization progress;
- UTC reset time.

Warning states:

- below 80%: normal;
- 80% through less than 100%: **Approaching cap**;
- remaining credits equal 0: **Cap reached**.

A zero-credit cap is treated as reached even when committed credits are zero,
because no new paid strict reservation can succeed.

### System Status

**Workspace → System Status → Strict verification effectiveness** also displays
the current live UTC guardrail status so operators can correlate historical
verification effectiveness with today's available budget.

## Refresh behavior

The Team page refreshes live status whenever its policy data reloads.

System Status already auto-refreshes every 10 seconds; the live daily budget is
loaded in the same refresh cycle.

## Permissions

The status is returned with the existing Workspace verification policy and uses
the existing `team:read` authorization boundary.

Owner and Admin users can change the guardrail through `team:manage`.
Analyst and Viewer users may see the current policy/status but cannot change it.

## Persistence

No schema migration is required.

Phase 25 derives status directly from the existing credit reservations created
by Phase 24 and the existing Workspace daily cap.
