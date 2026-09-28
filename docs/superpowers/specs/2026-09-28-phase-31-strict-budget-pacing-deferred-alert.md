# Phase 31 — Strict Budget Pacing Deferral Alerts

## Goal

Make forecast-aware Strict Verification pacing operationally visible. Phase 30 can
intentionally defer an automatic paid Strict probe with
`daily_budget_pacing_deferred`; Phase 31 lets operators route that event through
the existing alert delivery pipeline instead of discovering it only in run history.

## Rule

New alert rule type:

`strict_daily_budget_pacing_deferred`

The rule is probe-level. It may optionally scope to one Geo in the Monitor, or
watch all Monitor geographies when Geo is empty. It does not use an ASIN or
numeric threshold.

The rule fires when a verification event has:

`skipped_reason = daily_budget_pacing_deferred`

Manual-force probes remain unaffected because Phase 30 bypasses pacing for
manual force.

## Evidence

Alert event details preserve the normal Strict Verification evidence plus:

- `pacing_resume_at`
- `pacing_allowance_credits`

This keeps notifications auditable against the immutable completion-time run
metadata.

## Delivery and deduplication

No new notification transport is introduced. Email, Slack and generic webhook
delivery use the existing alert pipeline. Existing cooldown and event
deduplication semantics apply per rule, verification scope and Geo.

## Admin UI

Fantastic Admin → Alerts exposes **Strict deferred · forecast-aware pacing** as a
rule type. Because this is a probe-level rule, operators can leave Geo empty or
select one Monitor Geo.

## Safety invariants

- the alert does not change pacing decisions;
- it does not spend or reserve credits;
- it does not bypass the hard daily cap;
- it does not change manual-force behavior;
- it does not create ASIN-level duplicates for one deferred probe;
- notification failures do not change rank-run results.
