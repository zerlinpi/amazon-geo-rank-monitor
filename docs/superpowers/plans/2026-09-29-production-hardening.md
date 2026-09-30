# Production Hardening Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. The user authorized continuous execution, PR publication and conditional merge.

**Goal:** Deliver the existing Geo Rank product with reproducible production validation and operational guidance.

**Architecture:** Retain FastAPI/SQLAlchemy/Vue and pinned Fantastic Admin. Reusable CI workflows feed a stable validate job. Playwright drives the compiled UI against a local real backend with test-only deterministic providers.

**Tech Stack:** Python 3.12, Node 24, PostgreSQL 17, Redis 7, Playwright, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-29-production-hardening.md`

## Global Constraints

No new business subsystem, no published migration edits, no real provider calls in tests. Work only on chore/production-hardening. Preserve raw rank evidence and all tenant/billing/strict invariants. Report unavailable checks as BLOCKED rather than passing.

## Review Focus

- Failed or skipped jobs must never produce successful validate.
- Browser cookie/CSRF behavior and API errors must remain observable through real UI flows.
- Secrets in reset emails, notification failures and test artifacts must not enter logs.
- Compose must pass identical policy/billing settings to API, worker and scheduler.
- Managed+strict evidence must yield one geographic sample and no obsolete managed alert.

### Task 1: Repository cleanup and baseline

**Files:** .github/workflows/*, docs/hardening/PHASE32.md, the spec and this plan.
**Produces:** clean product workflow inventory and recorded baseline/branch classification.
- [ ] Remove the eight confirmed VOC workflows; preserve all SERP tests and sample keywords.
- [ ] Record git ancestry, migration chain, baseline tests and recent CI failure root cause.
- [ ] Validate with git diff --check and the existing full backend/frontend suites; commit cleanup together with baseline docs.

### Task 2: Backend reliability and security regressions

**Files:** backend/tests/test_production_hardening.py, test_postgres_integration.py, test_sso.py, analytics/alerts/rate_limit/email paths as needed.
**Consumes:** existing AppServices, repositories, immutable Alembic chain.
**Produces:** trustworthy geographic analytics/alerts, safe logs, bounded Redis readiness and repeatable migrations.
- [ ] Write failing tests for duplicate strict evidence, obsolete geo alerts, secret-bearing console email, Redis outage readiness and fresh PostgreSQL schema equivalence.
- [ ] Implement minimal fixes; preserve success-found/not-found semantics and raw history evidence.
- [ ] Make SSO signature corruption deterministic; audit existing strict/billing/rank coverage.
- [ ] Add real PostgreSQL race cases for reservations, cooldown, scheduled job/report idempotency, webhook/cache/SCIM boundaries where missing.
- [ ] Run pytest, Ruff, compileall and Alembic; verify actual integration results in CI.

### Task 3: Browser and business E2E

**Files:** frontend/package*.json, frontend/scripts/*, frontend/playwright.config.ts, frontend/e2e/*, backend/tests/e2e_server.py.
**Consumes:** the existing account API, RankWorker and compiled overlay.
**Produces:** npm ci/test/typecheck/build/test:e2e and a loopback-only fixture server.
- [ ] Add locked Playwright development dependency and an explicit typecheck command using upstream vue-tsc.
- [ ] Test UI login/dashboard and all requested history states across three timezones. Guard external browser requests.
- [ ] Exercise account/workspace→geo→monitor→worker→observations/snapshot→history→analytics with fake probes; assert three upstream probes for two ASINs across three geos and cache billing behavior.
- [ ] Run all browser cases against the production build; fix real behavior issues without hiding errors.

### Task 4: Validation, security and containers

**Files:** .github/workflows/{validate,backend-ci,frontend-ci,e2e-ci,security-ci,compose-ci}.yml, compose.yaml, Dockerfiles, .dockerignore, security tooling.
**Consumes:** Task 2 backend checks, Task 3 npm commands and browser fixtures.
**Produces:** stable validate status and offline container smoke.
- [ ] Convert component workflows to reusable calls; aggregate results with always() and explicit success checks.
- [ ] Run audits and redacted gitleaks across history/current tree; fix High/Critical findings or document release blockers.
- [ ] Compose includes DB, Redis, migration gate, API/worker/scheduler and static frontend; no insecure secret defaults in production config.
- [ ] CI builds/starts containers and checks health/readiness/Redis/heartbeats/frontend. No live provider credentials.

### Task 5: Production documentation and integration

**Files:** README.md, .env.example, CHANGELOG.md, SECURITY.md, docs/{DEPLOYMENT,UPGRADE,BACKUP_RESTORE,GITHUB_RULESET}.md, docs/hardening/PHASE32.md.
**Consumes:** tested commands/configuration and audit outcomes.
**Produces:** accurate deployment/release baseline and reviewable PR.
- [ ] Organize environment variables against AppSettings and frontend usage; document HTTPS/cookies, integrations, migration, backup, encryption retention and rollback.
- [ ] Inventory actual API contracts/performance/observability and record only concrete remaining risks.
- [ ] Complete full checks, fresh whole-branch review, and requested PR with all sections.
- [ ] Merge only with green Backend, Frontend, Validate, E2E, security/container checks and clean mergeability; verify final main.
- [ ] Clean only ancestor remote branches if tooling permits; record all capability blockers. No release or Phase 33 while readiness criteria remain unproven.
