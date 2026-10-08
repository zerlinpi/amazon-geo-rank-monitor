# Phase 34 — Strict Pacing Analytics

## Goal

Make Phase 30 forecast-aware Strict Verification pacing measurable in the
existing Workspace System Status verification analytics. This phase adds
observability only; it must not change credit reservations, provider selection,
pacing decisions, the hard budget cap, or manual-force semantics.

## API contract

`GET /api/v1/system/verification-analytics?hours=168` adds:

- `pacing_deferred`: count of completion-time verification events with
  `skipped_reason = daily_budget_pacing_deferred`, an automatic trigger
  (not `manual_force`), and a requested probe.
- `pacing_deferral_rate_pct`: `100 * pacing_deferred / automatic_requested`,
  rounded to two decimal places, returning 0 when the denominator is zero.
- `daily[].pacing_deferred`: the same event count aggregated by UTC completion
  date of the containing run. Billing-only dates receive an explicit zero.

`automatic_requested` retains the existing Phase 23 request classification.
All counts use persisted, immutable verification metadata, never extrapolated
from future forecast, and remain filtered by `owner_id` and the selected
time window. Per-run event counting avoids multiplying per-probe pacing
deferrals by the number of tracked ASINs.

## UI

Workspace → System Status shows two distinct cards:

- **Automatic pacing deferrals** (count in selected time window).
- **Automatic deferral rate** (percentage of automatically requested probes).

Daily verification activity adds **Pacing deferred**. The same existing time
window selector (24h, 7d, 30d, 90d) controls all metrics.

## Quality gates

- Verify zero denominators without errors.
- Verify one deferred automatic event is counted once.
- Verify a manually forced event is not classified as an automatic deferral,
  including defensively if its metadata contains a pacing skip reason.
- Verify that other tenants' runs do not appear in any metrics.
- Keep existing strict attempt, success, skip, spend, cache and alert
  behavior unchanged.
- Require backend tests, database integration, frontend build and all other
  repository-required Validate checks before merging.

No migration is needed because all new aggregates derive from existing stored
JSON event fields.
