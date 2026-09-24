# Production Scheduler & Migrations Implementation Plan

**Date:** 2026-09-24  
**Branch:** `feat/production-scheduler-migrations`  
**Base:** `feat/fantastic-admin-saas-ui`

## Goal

Close the main production-readiness gaps left after Phases 1-5 without changing the rank semantics or billing model.

## Delivered scope

1. Add a dedicated cron scheduler process for monitor definitions.
2. Validate monitor schedules as standard 5-field UTC cron expressions.
3. Generate deterministic job IDs from monitor + due UTC minute so a schedule slot is idempotent.
4. Dispatch only the latest due slot and avoid bulk catch-up after scheduler downtime.
5. Add tenant-scoped `GET /api/v1/monitors/{id}/history`.
6. Preserve `succeeded`, `partially_succeeded`, and `failed` rank outcomes on the database job instead of always marking completed workers as succeeded.
7. Use PostgreSQL `FOR UPDATE SKIP LOCKED` for concurrent production job claiming while retaining the SQLite compare-and-swap path for local tests.
8. Add Alembic and a baseline migration.
9. Allow production to disable runtime `Base.metadata.create_all()` with `AUTO_CREATE_SCHEMA=false`.
10. Gate Docker Compose API/worker/scheduler startup on a successful migration service.
11. Add scheduler, migration, partial-status, and monitor-history regression tests.

## Scheduling semantics

- Timezone: UTC.
- Syntax: 5-field cron only.
- First eligible execution: a cron slot at or after the monitor creation minute.
- Downtime recovery: only the latest due slot is considered; historical slots are not replayed automatically.
- Duplicate protection: deterministic UUIDv5 job ID per monitor/slot plus primary-key uniqueness.
- Manual runs remain independent and continue using random job UUIDs.

## Migration strategy

The first Alembic revision is a baseline for new installations. Existing databases created by earlier builds already contain the same Phase 1-5 tables and should be backed up, verified, then stamped to the baseline instead of replaying the baseline create operations.

Future schema changes must be introduced as explicit Alembic revisions.
