# Phase 29 — Strict Budget Forecast Runway Alert

## Goal

Add an urgency layer to the predictive daily Strict Verification budget alert.

Phase 28 answers: "Is the current pace projected to exhaust the cap today?"

Phase 29 answers: "Is that projected exhaustion close enough that operators
need to act now?"

## Alert rule

A new rule is available:

```text
strict_daily_budget_forecast_runway
```

The required threshold is a positive number of minutes, up to 1440.

Examples:

- 240: notify when forecast runway is four hours or less;
- 120: notify when forecast runway is two hours or less;
- 30: notify only for an urgent thirty-minute runway.

## Evaluation

The rule requires an available Phase 27 forecast with a concrete
`estimated_exhaustion_at` and `runway_minutes`.

It fires when:

```text
forecast.runway_minutes <= configured threshold
```

A forecast that predicts exhaustion later than the configured runway remains
silent.

The rule is Workspace-budget scoped and does not accept ASIN or Geo scope.

## Event evidence

The emitted event stores:

- configured runway threshold;
- actual forecast runway;
- daily limit;
- committed and remaining credits;
- credits/hour burn rate;
- projected EOD credits;
- projected utilization;
- estimated exhaustion timestamp;
- UTC reset timestamp.

The alert current value is the forecast runway in minutes.

## Notifications

The existing Email, Slack and allowlisted webhook channels are reused together
with cooldown, deduplication, encryption and delivery audit history.

This permits layered rules, for example:

- Phase 28 forecast-exhaustion rule with a long cooldown for early awareness;
- Phase 29 120-minute rule for urgent escalation;
- Phase 26 current-utilization rule for a separate hard-percentage warning.

## Fantastic Admin

**Workspace → Rank Alerts** exposes:

`Strict daily cap forecast within N minutes`

The threshold editor switches to minutes and is bounded to 1–1440.

## Safety

This alert is advisory only. It never changes policy or billing state and
cannot bypass the hard daily cap.
