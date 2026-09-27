# Phase 23 — Verification Analytics & Cost Attribution

## Goal

Make Strict Verification operationally measurable rather than only auditable per
run.

Workspace operators need to answer, for a selected time window:

- how often strict verification was requested;
- how often it succeeded or was skipped;
- how much activity was automatic versus manually forced;
- which anomaly triggers caused verification;
- why verification was skipped;
- how many failed managed Geo probes were recovered by strict;
- how often a compatible strict cache result avoided a paid browser probe;
- exactly how many credits were spent on successful strict upstream probes.

## API

Authenticated operators with `system:read` can query:

```http
GET /api/v1/system/verification-analytics?hours=168
```

`hours` accepts 1 through 2160 hours. The default is 168 hours (7 days).

The response contains:

- window start/end;
- run count with strict-verification activity;
- requested / attempted / succeeded / skipped counts;
- automatic / manual / unclassified requested counts;
- success and skip rates;
- strict cache-hit count;
- recovered managed-failure Geo count;
- normalized trigger counts;
- skip-reason counts;
- exact strict credits spent;
- strict provider credit rate;
- billed strict upstream probe count;
- credits per successful strict verification;
- estimated credits avoided by strict cache reuse;
- daily UTC activity rows.

The existing `/api/v1/system/verification-summary` endpoint remains available
for backward-compatible all-time counters.

## Effectiveness semantics

Every persisted verification event is classified as **manual** when its trigger
list contains `manual_force`; otherwise it is classified as **automatic**.

Dynamic triggers are normalized for aggregation:

- `rank_movement:<asin>:<delta>` -> `rank_movement`;
- `not_found_after_found:<asin>` -> `not_found_after_found`;
- `low_confidence:<ratio>` -> `low_confidence`.

Other trigger names remain unchanged.

A **recovered failed Geo** is a verification event that:

1. contains the `managed_probe_failed` trigger; and
2. finishes with `succeeded=true`.

A strict cache hit counts as a successful strict verification without an
upstream strict browser probe.

## Billing semantics

Cost attribution uses the append-only credit ledger, not rank-run estimates.

Only ledger rows satisfying all of these conditions count as strict spend:

- `entry_type=settlement`;
- `reference_type=auto_strict_verification`;
- matching workspace;
- settlement timestamp inside the requested window.

Reservations do not count as spend. Released reservations do not count as
spend. Failed strict browser attempts that release their reservation therefore
cost zero credits in this analytics view.

`credits_spent` is the absolute value of those settlement deltas.

`estimated_cache_savings_credits` is:

```text
strict cache hits × current strict per-probe credit rate
```

This is an estimate of avoided application credits, not a provider invoice or
cash-denominated accounting value.

`credits_per_success` divides exact strict credits spent by all successful
strict verification events in the window, including free cache hits. This makes
cache reuse visible as improved verification efficiency.

## Tenant isolation

Rank-run analytics and credit-ledger aggregation are both filtered by
`owner_id`. Global Prometheus counters remain a separate operator-level
surface and are not used to populate tenant analytics.

## UI

Fantastic Admin **Workspace → System Status** replaces the simple all-time
verification counter card with a windowed effectiveness dashboard.

Supported presets:

- last 24 hours;
- last 7 days;
- last 30 days;
- last 90 days.

The dashboard shows:

- requested volume and automatic/manual mix;
- success rate;
- recovered managed Geo failures;
- strict credits spent;
- strict cache hits and estimated credits avoided;
- credits per success;
- trigger breakdown;
- skip-reason breakdown;
- the most recent 14 active UTC days.

The existing System Status auto-refresh continues to refresh the selected
verification window.

## Persistence and migration

No schema migration is required.

Phase 23 derives analytics from existing immutable sources:

- `rank_runs.verification_metadata`;
- `credit_ledger_entries`.

This avoids maintaining a second mutable analytics copy and keeps historical
evidence traceable to the underlying run and billing records.
