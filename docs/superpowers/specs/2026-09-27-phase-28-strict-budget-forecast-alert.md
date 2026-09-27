# Phase 28 — Predictive Strict Daily Budget Alert

## Goal

Notify operators when the current UTC-day Strict Verification burn rate
predicts that the Workspace hard daily credit cap will be exhausted before the
next reset.

Phase 26 alerts on current utilization. Phase 28 acts earlier by consuming the
Phase 27 completion-time forecast.

## Alert rule

A new Monitor alert rule is available:

```text
strict_daily_budget_forecast_exhaustion
```

The rule has no numeric threshold.

It fires only when the completed run contains a daily budget forecast where:

- `forecast.available=true`;
- `forecast.estimated_exhaustion_at` is present.

A forecast that projects the Workspace to remain under the cap for the rest of
the UTC day does not emit an event.

## Scope

The underlying daily cap is Workspace-wide, so the predictive rule:

- does not accept ASIN scope;
- does not accept Geo scope;
- is attached to a Monitor only to reuse the existing completed-run alert
  evaluation and notification pipeline.

A single matching run produces one budget event for the rule.

## Event evidence

The event uses:

```text
event_type = strict_daily_budget_forecast_exhaustion
asin = VERIFICATION
details.scope = verification
```

Details retain:

- configured daily limit;
- currently committed credits;
- remaining credits;
- current credits/hour burn rate;
- projected EOD committed credits;
- projected EOD utilization;
- estimated exhaustion timestamp;
- forecast runway in minutes;
- UTC reset timestamp.

The alert current value is projected utilization percentage.

## Notification behavior

The rule reuses the existing notification system:

- Email;
- Slack Incoming Webhook;
- allowlisted generic HTTPS webhook;
- encrypted destinations;
- cooldown;
- per-run deduplication;
- delivery audit history.

The human-readable notification explicitly says the cap exhaustion is a
projection based on the current burn rate.

## Fantastic Admin

**Workspace → Rank Alerts** exposes:

`Strict daily cap forecast to exhaust today`

No threshold or Geo selector is required.

## Safety boundaries

- A forecast alert never changes Workspace policy.
- It never reserves or spends credits.
- The hard Phase 24 daily cap remains authoritative.
- The alert cannot fire until Phase 27 has a stable forecast sample.
- Later demand or cache behavior can invalidate an earlier projection, so the
  alert is advisory rather than a guarantee.

## Persistence and migration

No schema migration is required. Existing alert-rule and alert-event tables
store the new rule and its evidence.
