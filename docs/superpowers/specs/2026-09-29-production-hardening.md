# Phase 32 — Production Hardening & Repository Stabilization

User-approved scope: harden the existing product, remove unrelated VOC experiments, and establish a reproducible validation/release baseline. The full user specification was supplied on 2026-09-29. Do not add unrelated rank features or begin Phase 33.

## Baseline

- Start: `1ce080fdc6c3aacc9e9925a2f68707d5e9930f61`; branch `chore/production-hardening`.
- Clean main; no open PRs. Eight unrelated VOC workflows remain; collectors live on temporary branches.
- Backend baseline: 247 passed, 6 integration skips. Alembic has one head, `20260928_0021`.
- Frontend helper tests and compiled build exist; no npm lockfile, independent typecheck, browser E2E or unified required check.
- Recent main CI intermittently failed the SSO signature-tamper test. The fixture overwrites the first signature byte with a constant, which sometimes equals the original byte.
- Confirmed analytics defect: two runs with managed+strict evidence produce three geographic samples. The same raw evidence can cause obsolete managed-result alerts.
- Console email logging currently includes reset/verification links. Redis readiness is not checked. Compose misses several runtime settings and does not serve the frontend.

## Required outcomes

1. Remove only non-product VOC/review/Walking Pad workflows and references. Preserve all Amazon Search SERP, strict browser, geography, cache and competitive tests, including generic keyword fixtures.
2. Stable required check `validate`, depending on backend tests/lint/compile, PostgreSQL, Redis, migrations, frontend tests/typecheck/build, browser E2E, security and Compose smoke. No path-filter skips on this gate.
3. Fresh PostgreSQL migration to the single head and bounded downgrade/re-upgrade. Published migrations remain immutable.
4. Offline browser E2E in UTC, America/New_York and Asia/Singapore: login/dashboard, history filters/dates/shortcuts/clear, 50-row paging, lazy detail, empty/loading/error/retry. Add a real API→worker→database→history→analytics test using deterministic fake SERPs.
5. Audit strict, rank, billing, tenant and concurrency invariants; add tests for concrete uncovered risks. No real Oxylabs, Stripe, SMTP or proxy requests in tests.
6. Scan dependencies and git history; redact secret findings. Fix confirmed logging/secrets exposure. Any unresolvable High/Critical vulnerability is a release blocker with explanation.
7. Validate Compose and container startup ordering/health, worker and scheduler heartbeats, frontend load. Use CI for Docker when unavailable locally and report actual status.
8. Add CHANGELOG, deployment, upgrade, backup/restore, security and ruleset guides; organize all actual environment settings; preserve detailed README history behind a stable product introduction.
9. Delete remote feature branches only if their tip is an ancestor of main. Retain unarchived or active research branches. Document administration/capability blockers honestly.
10. Create the requested Phase 32 PR; merge only when all required checks pass and mergeability is clean. Release v1.0.0 only when all readiness criteria are proven; otherwise retain an Unreleased baseline with explicit blockers.

## Invariants

Organic/absolute/sponsored ranks stay separate. Provider error is not not-found. One SERP serves all ASINs. Managed is never independently IP-verified. Strict requires IP and delivery ZIP confirmation in the same context. Cache hits are not billable. Reservation concurrency cannot overspend. Tenant isolation is server-side. API keys are digested; passwords use Argon2; browser sessions use HttpOnly cookies. Generic webhooks require HTTPS and allowlist. Notification failure does not roll back a successful run. Analytics use persisted runs. Competitive capture costs no extra probe. Daily hard cap precedes pacing; manual force never bypasses kill switch, credits or hard cap.
