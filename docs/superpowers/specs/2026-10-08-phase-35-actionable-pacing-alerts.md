# Phase 35 — Actionable Strict Pacing Notifications

## Problem

Phase 31 stores `pacing_resume_at` and `pacing_allowance_credits` on
`strict_daily_budget_pacing_deferred` alert event details, but the existing
notification summary sent to email, Slack, and webhooks only contains the opaque
`daily_budget_pacing_deferred` reason. Operators cannot see the next estimated
pacing allowance without opening an individual run.

## Contract

For `strict_daily_budget_pacing_deferred` events, add these lines to the
existing shared notification summary **only when corresponding evidence exists**:

- `Estimated resume: <pacing_resume_at>`
- `Pacing allowance: <pacing_allowance_credits> credits`

The resume time is a forecast and must not be described as guaranteed.
The event's existing rule, event type, Geo, reason and run ID remain present.
Events without either field remain deliverable, without fabricated timestamps or
allowance values. The numeric allowance zero is a valid value and should display.

## Safety

- No changes to when pacing deferrals or alerts fire.
- No changes to credit reservations, caps, billing or retry behavior.
- All notification channels reuse the same summary formatting.
- No additional external calls or database schema changes.
- Existing cooldown, deduplication and Geo scoping remain unchanged.

## Verification

Backend regression tests assert that actual pacing evidence is present in the
delivered email summary and that missing evidence is safely omitted. Repository
Validate CI must pass for backend, frontend, E2E, security and Compose before
merging.
