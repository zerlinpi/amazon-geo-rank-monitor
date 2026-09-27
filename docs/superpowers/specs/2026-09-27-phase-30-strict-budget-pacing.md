# Phase 30 — Forecast-Aware Strict Budget Pacing

## Goal

Turn the existing Strict Verification daily budget forecast into an optional
automatic pacing guardrail.

Phases 27–29 predict and alert on early budget exhaustion. Phase 30 can defer
paid **automatic** Strict Verification probes when the current burn rate
predicts that the Workspace daily cap will be exhausted before the UTC reset.

The hard daily credit cap remains authoritative.

## Workspace policy

A new Workspace verification setting is stored:

```text
daily_budget_pacing_enabled = true | false
```

It defaults to `false`, so deploying Phase 30 does not change existing
Workspace behavior.

Pacing is meaningful only with a finite positive daily Strict Verification
credit cap.

## Pacing model

Pacing activates only when the Phase 27 forecast is stable and currently
predicts daily-cap exhaustion.

The current paced allowance follows a transparent linear UTC-day curve:

```text
allowance_now =
    floor(daily_credit_cap * elapsed_utc_day_seconds / utc_day_seconds)
```

Before a new paid automatic Strict probe:

```text
required = committed_credits + strict_probe_credit_cost
```

If:

```text
required > allowance_now
```

the probe is deferred with:

```text
skipped_reason = daily_budget_pacing_deferred
```

The estimated resume time is the point on the same linear allowance curve at
which `required` credits become available.

## Execution order

The decision order is deliberate:

1. evaluate whether Strict Verification is requested;
2. enforce the global runtime kill switch;
3. check the Strict SERP cache;
4. enforce per-run upstream probe budget;
5. evaluate forecast-aware pacing for automatic paid probes;
6. reserve credits;
7. execute the strict provider;
8. settle or release credits.

This means cached Strict results are never delayed by pacing because they do
not spend new credits.

## Manual force

A trigger containing `manual_force` bypasses pacing.

Manual force still obeys:

- the runtime global kill switch;
- the hard Workspace daily credit cap;
- prepaid credit availability;
- provider availability.

Pacing therefore cannot turn into a hidden block on an operator's explicit
verification request.

## Concurrency

A preflight pacing check alone is not sufficient when multiple workers execute
at the same time.

When pacing is active, the current paced allowance is also passed into the
existing credit reservation transaction as the temporary reference budget
limit. The billing account row lock serializes competing reservations on
PostgreSQL.

If another worker consumes the paced allowance first, the losing automatic
probe is recorded as `daily_budget_pacing_deferred` rather than spending past
the pacing line.

If the next probe would exceed the actual daily cap, the normal hard-cap
`daily_credit_budget_exhausted` result takes precedence.

## Evidence

Completed Rank Runs retain:

- whether pacing was enabled;
- the completion-time daily budget status;
- forecast state;
- pacing active/standby state;
- current paced allowance;
- estimated resume time;
- per-probe pacing skip reason and resume evidence.

This evidence is stored in existing verification JSON metadata.

## Fantastic Admin

**Workspace → Team → Automatic strict verification** adds a
**Forecast-aware pacing** switch.

The live daily-budget card shows whether pacing is active, the current paced
allowance, and the estimated resume time when the next automatic paid Strict
probe is deferred.

Run History shows the immutable pacing state captured when the run completed
and labels per-Geo pacing deferrals.

## Safety boundaries

- pacing is disabled by default;
- pacing never raises a budget;
- pacing never spends credits itself;
- pacing never bypasses the hard daily cap;
- pacing never delays compatible cache hits;
- pacing never delays `manual_force`;
- pacing does not change rank thresholds or anomaly detection;
- the forecast remains advisory and can move as demand changes.

## Persistence

Alembic revision `20260927_0020` adds:

```text
tenants.auto_strict_daily_budget_pacing_enabled
```

No new event or billing tables are required.
