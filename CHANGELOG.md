# Changelog

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
- Add Redis readiness checks and bounded connection timeouts. Keep `/health` as liveness.
- Remove secret-bearing email bodies and exception messages from logs/delivery records;
  return safe JSON errors with request IDs for unexpected API failures.
- Make the SSO invalid-signature fixture deterministic.
- Add actual browser regression tests, a network-free account→monitor→worker→analytics
  fixture, fresh PostgreSQL migration/rollback and parallel persistence cases.
- Ship a same-origin frontend container, migration startup gate, process heartbeats,
  complete environment reference and deployment/upgrade/backup/security runbooks.

No schema change. Existing migration head: `20260928_0021`. No release tag yet.
