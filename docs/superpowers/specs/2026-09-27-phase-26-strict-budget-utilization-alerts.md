# Phase 26 — Strict Daily Budget Utilization Alerts

## Goal

Warn operators before the Workspace daily Strict Verification credit guardrail
is exhausted.

Phase 25 makes current utilization visible. Phase 26 turns that live state into
a durable per-run audit snapshot and a proactive alert condition.

## Run evidence

When a managed rank run completes and a finite Workspace daily Strict
Verification credit budget is configured, the run stores the current UTC-day
budget state under:

`verification_metadata.auto_strict_daily_budget_status`

The snapshot contains:

- UTC window start;
- next UTC reset;
- configured credit limit;
- settled Strict Verification credits;
- in-flight reserved Strict Verification credits;
- total committed credits;
- remaining credits;
- utilization percentage.

The value is captured after strict verification reservations for the run have
been settled or released, so the run records the operational state that existed
when alert evaluation began.

Unlimited Workspaces store no utilization snapshot because there is no finite
threshold to approach.

## Alert rule

A new Monitor alert rule is available:

```text
strict_daily_budget_utilization
```

The rule accepts a required threshold from 1 through 100 percent.

Example:

```text
threshold = 80
```

fires when the completion-time daily Strict Verification budget snapshot is at
or above 80%.

The rule is Monitor-triggered but evaluates Workspace-wide budget state. It
therefore does not accept ASIN or Geo scope.

## Notification semantics

The rule reuses the existing alert delivery pipeline:

- Email;
- Slack Incoming Webhook;
- allowlisted generic HTTPS webhook;
- encrypted destination storage;
- cooldown;
- per-run deduplication;
- delivery-failure audit history.

The emitted event uses:

```text
event_type = strict_daily_budget_utilization
asin = VERIFICATION
details.scope = verification_budget
```

Event details include the threshold, limit, settled, reserved, committed,
remaining, utilization, window start, and reset time.

## UI

**Workspace → Rank Alerts** exposes:

`Daily Strict budget reaches N%`

with a 1–100% threshold control.

**Workspace → Run History** shows the completion-time daily utilization snapshot
alongside the existing Strict Verification evidence.

Recommended starting thresholds:

- 80% for an early warning;
- 95% for an urgent warning.

Separate rules may be configured when both notification levels are useful.

## Persistence and migration

No schema migration is required.

The budget snapshot is stored in the existing JSON verification metadata on the
rank run, and alert rules/events use the existing alert tables.

## Safety boundaries

This phase does not change the hard Phase 24 guardrail.

- Alerts do not reserve or spend credits.
- Manual force still cannot bypass the hard daily cap.
- A missing or unlimited daily cap does not emit utilization alerts.
- Notification failure never changes the completed rank job state.
