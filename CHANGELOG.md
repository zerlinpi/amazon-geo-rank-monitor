# Changelog

## Unreleased — Free mode and operator-managed credits

- Default to `BILLING_MODE=free` across API, Worker and automatic Strict checks:
  zero application balance is valid, probes do not reserve or deduct app credits,
  and new online checkout is disabled. Existing balances and signed payment
  callbacks are retained. External provider and hosting fees still apply.
- Keep `prepaid` available with either administrator funding or Stripe checkout.
  Show the active mode, rates, recoverable billing errors and adjustment details.
- Add the host-only `agrm-credits` CLI to locate workspaces by email, inspect
  balances and preview/apply audited increases, decreases or absolute balances.
  Exact request replay is idempotent; adjustments cannot consume reserved credits.
- Add migration `20261013_0023` for nullable credit ledger audit details, preserving
  existing balances/history. Downgrading this revision deletes audit details.
- Put the Chinese materials checklist, installation, first monitoring run,
  account administration, daily operation, backup, upgrade and troubleshooting
  steps directly in README. Align staging checks with the selected billing mode.

Existing paid deployments must explicitly set `BILLING_MODE=prepaid` to retain
charging. Drain work before changing mode and restart all backend processes
together. In free mode, positive credit budgets/pacing do not limit upstream
spend; use provider limits, monitor frequency and per-run probe caps. A zero
daily budget still blocks new automatic/forced Strict calls.

## Unreleased — Operational rank acceptance

- Enforce organic search-depth boundaries in target matching and align competitor
  channel ranks with monitor results.
- Continue managed pagination using observed organic counts, order returned pages,
  support documented total-page metadata, and reject missing/duplicate pages,
  failed/partial parsing, contradictory pagination and malformed organic records.
- Preserve documented relative-position sponsored entries and fail incomplete
  Managed/Strict scans at the 20-page ceiling instead of reporting false not-found.
- Version provider cache identities so earlier parser results are not reused.
- Add regression coverage and a Chinese operational acceptance record separating
  offline/CI evidence from still-unverified live deployment and signed Windows delivery.

No schema change or dependency update. Historical records are retained. Accurate
depth collection may use more upstream page requests; application credit rates
are unchanged, and upstream costs must be checked before live rollout.

## Unreleased — Practical monitor workflow

- Fix browser Geo Profile creation returning 422 because the API required an ID
  that the repository replaces with its own generated ID. Preserve legacy input
  compatibility, field validation and workspace isolation.
- Simplify region/monitor forms with advanced settings and UTC frequency presets;
  keep custom cron and make existing monitors editable without resetting their
  automatic verification overrides or deleting history.
- Replace the wide fixed monitor action column with responsive, searchable cards.
- Show recent monitor jobs and automatically refresh active job status, with
  recoverable read failures and direct links to exact run details.
- Guard repeated queue submissions while a request is pending and treat cancelled
  strict confirmation as cancellation, not an error.
- Add browser journeys for mobile creation/edit/run/results, save/load recovery,
  policy preservation and status-refresh failures without duplicate submission.

No schema migration or new dependencies. Provider calls remain explicit manual
runs or configured schedules; external production readiness is a separate check.

## Unreleased — Email delivery status

- Record missing SMTP as a failed email alert/report attempt instead of a false
  success; preserve report idempotency and independent webhook delivery.
- Add an authenticated, read-only notification configuration endpoint that exposes
  no SMTP secrets and performs no network probes.
- Show email configuration, request failure/retry and delivery error feedback in
  Rank Alerts, Analytics & Reports and System Status.
- Preserve privacy-safe registration/recovery responses and token-safe logging.
- Cover configuration, delivery failure and recovery in backend and browser tests.

No schema change. Current migration head remains `20261008_0022`.
Existing delivery history is retained; failed attempts are not automatically replayed.

## Unreleased — Phase 33 staging release readiness

- Add `agrm-readiness` for secret-safe production-style configuration checks.
- Add bounded, non-transactional SMTP and Stripe live authentication checks.
- Add explicit opt-in managed/Strict paid provider probes for controlled staging only.
- Add a manual-only GitHub Actions `Staging Readiness` workflow that verifies
  deployed HTTPS frontend/API health before integration checks.
- Upload sanitized readiness JSON as short-lived workflow evidence.
- Add a staging readiness runbook and keep release/tag creation manual.
- Refresh the pinned Fantastic Admin security patch for `shell-quote` 1.12.0
  and `source-map-js` 1.2.2.
- Split frontend security auditing into a zero-exception production dependency
  gate plus an exact development-only exception for unpatched
  `GHSA-vfj7-8cjw-p6xm` (`braces`).

No schema change. Existing migration head remains `20260928_0021`.
A release still requires the normal exact-commit `validate` gate plus staging
evidence; Phase 33 does not create `v1.0.0` automatically.

## Unreleased — Phase 32 production hardening

- Remove nine temporary review/VOC research workflows from the product branch.
- Add a stable `validate` gate covering reusable backend, PostgreSQL, Redis,
  frontend, browser E2E, security and Docker Compose workflows on every PR.
- Lock backend and frontend dependencies; apply a reviewed security patch to the
  pinned Fantastic Admin revision without replacing the UI framework.
- Prefer successful strict evidence once per run/ASIN/geo in analytics and alerts;
  preserve both raw managed and strict observations in history.
- Make probe-cache writes and counters atomic; reject stale responses overwriting
  fresh cache entries. Make ignored and paid webhook retries concurrency safe.
- Preserve competitor evidence for queued Worker runs.
- Scope operations queue, dead-letter retries and verification metrics to the current
  workspace; hide other tenants' job IDs and errors in shared worker status.
- Preserve client-specific authentication limits through explicit proxy trust boundaries;
  route SCIM through the same-origin ingress and suppress callback query access logs.
- Refresh worker/scheduler liveness during long jobs and blocking report delivery
  without changing job status or processed counters.
- Add Redis readiness checks and bounded connection timeouts. Keep `/health` as liveness.
- Remove secret-bearing email bodies and exception messages from logs/delivery records;
  return safe JSON errors with request IDs for unexpected API failures.
- Make the SSO invalid-signature fixture deterministic.
- Add actual browser regression tests, a network-free account→monitor→worker→analytics
  fixture, fresh PostgreSQL migration/rollback and parallel persistence cases.
- Ship a same-origin frontend container, migration startup gate, process heartbeats,
  complete environment reference and deployment/upgrade/backup/security runbooks.

No schema change. Existing migration head: `20260928_0021`. No release tag yet.
