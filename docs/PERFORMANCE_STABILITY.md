# Performance, stability, diagnostics and release gate

This runbook covers the **current multi-service web SaaS**, not a Windows desktop executable. Its production request path is: browser → TLS edge → frontend nginx → FastAPI → PostgreSQL / Redis / job queue → worker / scheduler → provider. Diagnose the failing layer before tuning unrelated code.

## Operational objectives and limits

Define service-level objectives for your deployment before selecting worker counts. The following are **recommended test targets, not measured production results or guarantees**:

| Area | Suggested acceptance target | Evidence |
|---|---|---|
| UI responsiveness | No sustained main-thread blocking during normal history-page navigation | Browser Performance panel, realistic production build |
| History list | Bounded result size and stable cursor; inspect P50/P95 API latency under expected data volume | `/api/v1/runs/page`, request IDs and database traces |
| Full legacy history | Database queries should not grow with the requested number of runs | `test_run_history_batching.py` |
| Recovery | Restarting worker during a non-billed test eventually recovers eligible leased jobs without duplicate settlement | Lease tests, worker metrics and audit |
| Reliability | No uncontrolled process crashes during a defined soak interval; failure recovery documented | Docker logs, health probes, alerts |
| Security | No plaintext secrets in logs/artifacts and no cross-tenant reads | CI security + tenancy tests |
| Release | Exact PR head and merge-base checked; every required GitHub check returns `success` | Actions and PR mergeability |

Do not claim “zero bugs”, “zero crashes”, “always smooth” or “best possible performance” solely from a green build. Use workloads and data sizes that resemble production to derive verified targets.

## 1. Performance baselines

Record the Git commit, migration head, platform, number of monitors / runs / observations, CPU, RAM, worker replicas, Redis and PostgreSQL version, browser/device, number of geo profiles and provider mode. Compare the same workload across revisions.

For application liveness and availability:

```sh
docker compose ps
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
docker compose exec -T api alembic current
docker compose logs --since=15m --tail=200 api worker scheduler frontend
```

Run this on an **authorized** production host; never publish full logs with tokens, email addresses, SSO redirect codes or other sensitive information. Do not run test reset commands against production PostgreSQL or Redis.

## 2. Slow Run History

The modern `GET /api/v1/runs/page` endpoint returns only summaries (bounded to 1–100) and an opaque cursor. The legacy `RankRepository.list_runs` returns complete details with observations and snapshots and should be used only for compatibility or small result sets.

Phase 39 changes legacy `list_runs` from **one list query plus three per-run queries** (including `get_run`) to **three SQL reads total** for a nonempty page: runs, batched observations, batched snapshots. It preserves all fields and existing detail ordering. The empty case performs one query. `test_run_history_batching.py` asserts the query count and tenant isolation. This is a query-count improvement, **not a measured latency claim**.

Performance debugging steps:

1. In Chrome DevTools → Network, check whether the delay is static JS/CSS, `/api/v1/runs/page`, `/api/v1/runs/{id}` or an unrelated endpoint.
2. In PostgreSQL inspect slow query plans using parameterized `EXPLAIN (ANALYZE, BUFFERS)` on an authorized non-sensitive dataset; compare row counts and index access. Do not paste secrets into SQL logs.
3. Limit history pages and CSV exports; prefer Run History summary pages and request details on demand. `/api/v1/runs/page` already uses a tenant/time/index path.
4. For high cardinality data, profile queries and memory before adding speculative indexes or caching private responses. Every schema index adds write and migration costs.
5. For a regressed deployment, compare before/after metrics using the same dataset and release SHA.

## 3. Browser stutter, animation, flicker or apparent crashes

- Test the **actual production** `frontend/dist` bundle in Chrome and Edge, not just development HMR. Run frontend unit tests, typecheck, build and Playwright E2E.
- Use Chrome Performance to identify Long Tasks and layout shifts. Avoid animating layout-heavy `width`, `height`, `top` or complex shadows on large lists; prefer compositor-friendly `transform` and `opacity` where appropriate.
- Respect `prefers-reduced-motion` for nonessential transitions. Avoid stacking repeated polling, duplicate event listeners, uncontrolled WebSocket reconnection loops or rendering thousands of row details at once.
- If the browser tab reloads or disappears, inspect DevTools errors and memory usage, extension interference, OS event logs and proxy/API responses. Do not label a 502 API outage as a frontend crash.
- For upstream Fantastic Admin changes, preserve its pinned version and reviewed security patch. `frontend/scripts/sync-upstream.mjs` uses the pinned checkout; unreviewed upstream upgrades can change the UI or security model.

## 4. Worker and provider failures

- `/ready` protects database/Redis readiness; it cannot guarantee upstream provider or SMTP reachability.
- Check `GET /api/v1/system/workers`, `/queue` and `/dead-letters` with `system:read`. Compare last heartbeat, lease expiry, queue age, attempt count and retry availability.
- Provider rate limits, blocks, CAPTCHA and ZIP/IP verification failure should remain explicit failures, not fabricated not-found observations.
- Do not raise concurrency without first checking allowed provider rate, credit reserve/settlement, upstream cost and database pool limits.
- If a job is in DLQ, investigate its error before requeue. A new attempt can consume real credits.
- Keep `WORKER_ID` and `SCHEDULER_ID` unique per replica and ensure NTP/clock synchronization.

## 5. Resource diagnostics

Check system resources using your infrastructure observability stack; correlate metrics with request IDs.

| Symptom | First measurements | Safe initial action |
|---|---|---|
| Slow API but stable UI | P95 route latency, SQL execution time, DB pool contention | Bound pages and profile queries |
| High PostgreSQL CPU | Sequential scans, slow query log, vacuum/index health | Explain on representative dataset |
| Worker backlog | Available jobs, retries, provider quotas, worker heartbeats | Fix provider/worker failures before scaling |
| Login loop | HTTPS, cookie secure/samesite, CSRF/CORS, clock | Correct domain/proxy settings |
| Frontend blank screen | Static 404, JS errors, CSP, base URL, nginx proxy | Rebuild same pinned revision and verify ingress |
| Repeated renderer jank | Main-thread long tasks, memory, list size, transitions | Remove duplicate work; virtualize only after profiling |
| Out-of-memory | Container memory, browser heap snapshots | Bound response sizes and find leaks |

## 6. Validation commands

```sh
# From repository root (Linux/macOS/WSL2):
python -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.lock
.venv/bin/pip install --no-deps -e backend
(cd backend && ../.venv/bin/python -m pytest -q && ../.venv/bin/ruff check src tests)
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
docker compose config --quiet
```

Do not infer CI success from these commands unless they actually ran. PostgreSQL and Redis integration tests require the disposable services described in [DEPLOYMENT.md](DEPLOYMENT.md). Browser E2E requires the configured browser runtime and isolated fake providers. Before merging, check the GitHub **Validate** workflow for that exact PR and ensure every required job is **success** (not cancelled/skipped/pending).

## 7. Production release / rollback checklist

1. Review changelog and diff; confirm no accidental billing, auth, tenant, provider or migration behavior changes.
2. Require backend unit and database integration tests, Redis tests, frontend unit/typecheck/build, browser E2E, dependency/secret audit, Compose smoke and final validate.
3. Back up database and all stable encryption keys; test restoring into a nonproduction environment.
4. Deploy exact reviewed SHA, run the documented migration, verify readiness, TLS, session login, worker/scheduler heartbeat, data access, sample history, alerts and report configuration.
5. Observe the canary interval before broader rollout. Monitor task retries, duplicate delivery, credit settlement, UI errors and resource use.
6. If validation fails, pause rollout and revert **code or schema via the documented compatible path**; never force-push main or blindly downgrade the entire schema.

See [Upgrade and rollback](UPGRADE.md), [Staging Readiness](STAGING_READINESS.md), and [Windows release options](WINDOWS_RELEASE.md).
