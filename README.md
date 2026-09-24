# Amazon Geo Rank Monitor

Amazon geographic organic-rank monitoring service. It observes the same Amazon keyword from multiple geographic profiles, locates one or more ASINs in each SERP, and calculates a weighted organic rank.

## Scope

This repository is intentionally focused on Amazon rank monitoring. Amazon Ads bidding, listing optimization, inventory, repricing, and review scraping are out of scope.

The architecture uses a Hybrid provider model:

- **Managed monitoring:** Oxylabs Amazon Search for routine, structured SERP collection.
- **Strict verification:** Playwright + residential proxy verification where the requested IP geography and Amazon Deliver-to location are independently confirmed before the SERP result is accepted.

Managed mode must not be described as strict IP verification. The Oxylabs adapter records the requested IP geography as metadata while using the delivery postal code for the managed Amazon search geography.

## Rank semantics

The system keeps three concepts separate:

- `organic_rank`: position among organic products only; this drives the weighted score.
- `absolute_rank`: observed mixed product-card position including sponsored placements.
- `sponsored_rank`: position among sponsored results when present.

For Oxylabs managed results, provider `pos` is retained as an observed mixed SERP position; organic rank is derived from the ordered organic result collection so sponsored placements do not inflate the organic rank.

If an ASIN is not found within `search_depth`, the stored values are:

```text
found = false
organic_rank = null
effective_rank = search_depth + 1
```

A provider failure is an error, not an ASIN-not-found result.

## One SERP, many ASINs

The data-collection unit is a SERP probe, not an ASIN. A single query for:

```text
marketplace + keyword + geo profile + device + search depth
```

is matched against every requested ASIN. Therefore 2 ASINs across 3 geographic profiles require 3 provider probes, not 6.

## Weighted rank

For successful observations:

```text
weighted_rank = sum(effective_rank_i * weight_i) / sum(weight_i)
```

Weights are normalized mathematically and do not need to sum to 1 or 100. The raw regional observations are always retained alongside the weighted score. Confidence currently represents the share of configured geographic weight covered by successful probes.

## Managed monitoring

The default `OxylabsRankProvider` uses Oxylabs Amazon Search parsed results.

Managed mode is optimized for routine monitoring and bulk collection. It records:

- requested IP geography from the GeoProfile as intent;
- Amazon delivery postal code used for the managed request;
- `ip_geography_verified = false`.

This distinction is deliberate: managed results must not be presented as proof that the exit IP postal code was independently verified.

## Strict geographic verification

Strict mode is implemented by `StrictBrowserRankProvider` and `PlaywrightAmazonBrowserClient`.

Current strict flow:

```text
GeoProfile
   |
   v
Residential proxy with sticky session
   |
   v
Verify observed exit-IP geography
   |
   v
Same isolated Playwright BrowserContext
   |
   v
Open Amazon and set Deliver-to ZIP
   |
   v
Confirm requested ZIP is displayed
   |
   v
Search keyword and collect SERP cards
   |
   v
Organic / sponsored separation
```

A strict result is accepted only when both the requested IP geography and requested Amazon delivery ZIP are confirmed.

Current strict constraints:

- `amazon.com` only;
- US ZIP-level residential proxy targeting only;
- desktop browser only;
- one isolated BrowserContext per strict probe;
- CAPTCHA / robot-check pages produce an explicit blocked error;
- the implementation does not solve CAPTCHA, use stealth plugins, spoof fingerprints, or attempt to bypass anti-bot controls.

Strict verification is intended for manual checks, anomalies, and high-confidence validation. Routine scheduled monitoring should use managed mode.

## Local development

Requirements: Python 3.12+.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
cp ../.env.example .env
PYTHONPATH=src python -m pytest -q
ruff check src tests
```

Configure geographic profiles from `config/geo_profiles.example.yaml`.

For real managed Oxylabs calls:

```env
OXYLABS_USERNAME=...
OXYLABS_PASSWORD=...
```

For strict residential-proxy verification:

```env
RESIDENTIAL_PROXY_USERNAME=...
RESIDENTIAL_PROXY_PASSWORD=...
RESIDENTIAL_PROXY_SERVER=http://pr.oxylabs.io:7777
```

Install a Chromium runtime before executing real strict checks:

```bash
playwright install chromium
```

Provider credentials are not required to import the package or run the offline unit tests.

## Current implementation phase

Implemented:

- provider-neutral rank core and strict geographic verification;
- tenant-scoped REST, API keys, database worker and MCP runtime;
- prepaid credits, reserve/settle accounting and Stripe Checkout/webhooks;
- Fantastic Admin Basic SaaS console;
- cron-based monitor scheduling with idempotent time-slot dispatch;
- PostgreSQL-safe worker claiming with `FOR UPDATE SKIP LOCKED`;
- monitor-specific run history;
- Alembic production schema migrations;
- Docker Compose migration gate, API, worker and scheduler services;
- GitHub Actions tests, Ruff checks, and PostgreSQL integration coverage;
- least-privilege API-key scopes, database readiness, and worker heartbeats;
- leased rank jobs, automatic retries, stuck-job recovery, dead-letter queue, and Prometheus-compatible operations metrics.

The complete architecture is documented in `docs/superpowers/specs/2026-09-24-amazon-geo-rank-saas-design.md`.


## API, worker, and MCP runtime

Phase 3 exposes the same rank application through authenticated REST, a database-backed worker, and the official MCP Python SDK v2.

Required SaaS secret:

```env
API_KEY_PEPPER=replace-with-a-long-random-server-secret
```

Bootstrap the first tenant and API key:

```bash
cd backend
agrm-bootstrap --name "My Workspace"
```

The plaintext API key is printed once. The database stores only its display prefix and HMAC-SHA256 digest.

Start REST:

```bash
agrm-api
```

REST requests use:

```http
X-API-Key: agrm_...
```

Run one queued database job:

```bash
agrm-worker --once
```

Or run the worker continuously:

```bash
agrm-worker
```

For a local MCP stdio server, bind the process to one tenant:

```env
MCP_TENANT_ID=<tenant uuid>
```

Then run:

```bash
agrm-mcp
```

The local process boundary is the tenant security boundary for stdio. Streamable HTTP is intentionally not exposed by the CLI until an OAuth 2.1 `AuthSettings`, `TokenVerifier`, and access-token-to-tenant resolver are configured. A SaaS API key is not treated as an OAuth bearer token.

### REST endpoints

- `GET /health`
- `GET /ready`
- `POST/GET /api/v1/geo-profiles`
- `POST/GET /api/v1/monitors`
- `GET /api/v1/monitors/{id}`
- `GET /api/v1/monitors/{id}/history`
- `POST /api/v1/monitors/{id}/run`
- `GET /api/v1/jobs/{id}`
- `POST /api/v1/rank/check`
- `GET /api/v1/runs/{id}`
- `GET/POST/DELETE /api/v1/api-keys`
- `GET /api/v1/system/workers`
- `GET /api/v1/system/queue`
- `GET /api/v1/system/dead-letters`
- `POST /api/v1/system/dead-letters/{job_id}/requeue`
- `GET /api/v1/system/metrics`

All tenant-owned lookups are filtered server-side. A resource owned by another tenant is returned as not found.

### MCP tools

- `check_rank`
- `list_geo_profiles`
- `create_monitor`
- `run_monitor`
- `get_rank_run`
- `get_rank_history`

MCP tools call the same application services used by REST; there is no duplicate ranking implementation.


## Prepaid credits and Stripe

Rank usage is billed by actual SERP probe, not by ASIN. The default configurable rate card is:

- managed SERP: 1 credit per geographic probe;
- strict browser-verified SERP: 5 credits per geographic probe.

A request reserves the maximum probe cost before provider work. Only successful geographic probes are settled; unused reserved credits are released.

Credit packs are disabled by default because their prices are business configuration. Set the corresponding `CREDIT_PACK_*_AMOUNT_MINOR` values above zero to publish them.

Stripe configuration:

```env
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_SUCCESS_URL=https://app.example.com/billing/success
STRIPE_CANCEL_URL=https://app.example.com/billing
CREDIT_PACK_STARTER_AMOUNT_MINOR=...
CREDIT_PACK_GROWTH_AMOUNT_MINOR=...
CREDIT_PACK_SCALE_AMOUNT_MINOR=...
```

The browser success redirect never grants credits. Purchased credits are granted only after a signed Stripe webhook reports a paid Checkout Session. The internal append-only credit ledger remains the source of truth for application credits.

Billing REST endpoints:

- `GET /api/v1/credits`
- `GET /api/v1/credits/ledger`
- `GET /api/v1/billing/packs`
- `POST /api/v1/billing/checkout`
- `POST /api/v1/billing/webhook`

MCP exposes `get_credit_balance` as read-only; it does not expose ledger mutation or Stripe operations.


## SaaS frontend

The SaaS console uses Fantastic Admin Basic `core-element-plus` as its only UI foundation. The upstream source is pinned rather than copied wholesale into this repository:

- upstream: `fantastic-admin/basic`
- version: `v6.4.0`
- revision: `4cf1d0f92c3c7a8651bc41c6c3b65aabbde30af1`
- license attribution: `THIRD_PARTY_NOTICES.md`

Product-specific files live under `frontend/overlays/`. The sync script clones the exact pinned upstream revision into the ignored `frontend/.vendor/fantastic-admin` directory and overlays the Amazon Geo Rank Monitor pages before running the upstream build.

Requirements: Node.js 24.15+ and Git.

```bash
cp frontend/.env.example frontend/.env
npm --prefix frontend run sync
npm --prefix frontend run dev
```

Production build:

```bash
VITE_AGRM_API_BASEURL=https://api.example.com npm --prefix frontend run build
```

The generated static bundle is copied to `frontend/dist`.

The current authentication surface uses a Workspace API Key because the backend deliberately has no password-user model yet. Fantastic Admin route authentication is enabled, the key is sent as `X-API-Key`, and provider/Stripe secrets are never exposed to the browser.

Main console pages:

- Dashboard
- Rank Explorer
- Monitors
- Geo Profiles
- Run History
- Credits & Billing
- API Keys
- MCP Setup


## Scheduled monitors

A monitor may include a standard 5-field cron expression. Schedules are interpreted in UTC.

Example:

```text
0 */6 * * *
```

Run the scheduler once:

```bash
agrm-scheduler --once
```

Or run it continuously:

```bash
agrm-scheduler
```

The scheduler dispatches only the latest due cron slot. It does not backfill every missed slot after downtime. Each slot receives a deterministic job UUID derived from the monitor ID and scheduled UTC minute, so repeated scheduler scans and multiple scheduler instances do not intentionally create duplicate jobs for the same slot.

## Database migrations

Local development keeps `AUTO_CREATE_SCHEMA=true` by default for fast SQLite setup. Production should run Alembic and set `AUTO_CREATE_SCHEMA=false`.

For a new database:

```bash
cd backend
alembic -c alembic.ini upgrade head
```

The included Docker Compose stack runs a one-shot `migrate` service before the API, worker and scheduler start.

For an existing database created by an earlier Phase 1-5 build, take a backup and verify that its schema matches the current SQLAlchemy models before stamping the baseline revision:

```bash
cd backend
alembic -c alembic.ini stamp 20260924_0001
```

Do not run the baseline `upgrade` against an already-populated schema that was created with `Base.metadata.create_all()`; stamp it only after verification.


## Production API boundary

Authenticated `/api/v1/*` requests support a per-process API-key rate limit configured with:

```env
API_RATE_LIMIT_PER_MINUTE=120
```

Responses include `X-Request-ID`. Clients may provide their own `X-Request-ID` up to 128 characters; otherwise the API generates one.

HTTP and validation failures keep the existing `detail` field for compatibility and also return a machine-readable envelope:

```json
{
  "detail": "API key required",
  "error": {
    "code": "AUTH_REQUIRED",
    "message": "API key required",
    "request_id": "..."
  }
}
```

The built-in limiter is intentionally process-local. Multi-replica deployments should also enforce a shared rate limit at the API gateway or replace the limiter with a shared store.

Monitor lifecycle endpoints now include:

- `PATCH /api/v1/monitors/{id}`
- `DELETE /api/v1/monitors/{id}`

PATCH supports partial updates to monitor metadata, ASINs, geo profiles, provider mode, schedule, search depth, and enabled state. Tenant ownership is revalidated for all referenced geo profiles.


## Least-privilege API keys

API keys now carry explicit scopes. Existing/bootstrap keys use `*` for backward-compatible full access. New automation keys should request only what they need.

Available scopes:

- `geo:read`, `geo:write`
- `monitors:read`, `monitors:write`
- `rank:read`, `rank:write`
- `billing:read`, `billing:write`
- `keys:manage`
- `system:read`, `system:write`
- `*` for full access

Example:

```json
{
  "name": "rank-reporting",
  "scopes": ["geo:read", "monitors:read", "rank:read"]
}
```

A valid key that lacks a required scope receives HTTP 403 with error code `FORBIDDEN`.

## Readiness and worker heartbeats

`GET /health` is a process liveness check. `GET /ready` executes `SELECT 1` against the configured application database and returns HTTP 503 when the database cannot be reached. Docker Compose uses `/ready` for the API healthcheck.

Rank workers persist heartbeat state in `worker_heartbeats`. Authorized operators can inspect it with:

```http
GET /api/v1/system/workers
X-API-Key: <key with system:read>
```

Each heartbeat includes worker ID, status, last job ID/error, processed-job count, start time, and last-seen time. Set a unique `WORKER_ID` per worker replica.

## PostgreSQL CI

Backend CI starts PostgreSQL 17 and executes a real concurrent claiming test against `FOR UPDATE SKIP LOCKED`. This complements the default SQLite unit suite and protects the production multi-worker path from regressions.

Schema revision `20260924_0002` adds API-key scopes and worker heartbeat state. Existing databases already stamped at `20260924_0001` should run:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Job reliability and dead-letter recovery

Rank jobs use a database-backed lease rather than assuming a worker will always exit cleanly. A claim records the worker ID and a lease expiry. While provider work is running, the worker renews the lease periodically.

If a worker process disappears, another worker detects the expired lease and recovers the job. Failed attempts use exponential backoff until `JOB_MAX_ATTEMPTS` is exhausted; the job then moves to `dead_letter` and remains visible for operator review.

Default controls:

```env
JOB_MAX_ATTEMPTS=3
JOB_LEASE_SECONDS=900
JOB_RETRY_BASE_SECONDS=30
JOB_RETRY_MAX_SECONDS=900
```

The retry delay is capped exponential backoff. A job is not claimable before its `available_at` time. Total provider failure is retried; partial rank results remain a completed `partially_succeeded` run.

Billing reservations are attempt-specific. When a stale lease is recovered, any still-reserved credits for that abandoned attempt are released before the next attempt is claimed.

Operators with `system:read` can inspect queue state and the DLQ. Requeueing a dead-letter job requires `system:write` and resets its attempt counter.

The Fantastic Admin console exposes this under **Workspace → System Status**, including queue counters, worker/scheduler heartbeats, last errors, and dead-letter requeue actions.

## Prometheus-compatible metrics

Authenticated operators can scrape:

```http
GET /api/v1/system/metrics
X-API-Key: <key with system:read>
```

The endpoint uses Prometheus text exposition and currently emits:

- `agrm_rank_jobs{status=...}`
- `agrm_queue_oldest_pending_age_seconds`
- `agrm_service_heartbeat_age_seconds{worker_id,worker_type,status}`
- `agrm_service_processed_jobs_total{worker_id,worker_type,status}`

Schedulers now emit the same persistent heartbeat records as rank workers. Set a unique `SCHEDULER_ID` for each scheduler replica.

## Phase 9 migration

Schema revision `20260924_0003` adds rank-job availability, worker ownership, lease expiry, and maximum-attempt fields.

Existing production databases should run:

```bash
cd backend
alembic -c alembic.ini upgrade head
```

New databases continue to run all migrations through the existing Docker Compose migration gate.
