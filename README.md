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
- leased rank jobs, automatic retries, stuck-job recovery, dead-letter queue, and Prometheus-compatible operations metrics;
- tenant audit trails, API-key usage/IP statistics, and Redis-backed multi-replica rate limiting.

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
- `GET /api/v1/system/audit`

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


## Audit trail and API key usage

Every authenticated REST request under `/api/v1/*` writes a tenant-scoped audit event after the response is produced. Audit events store metadata only:

- API key ID, never the plaintext key;
- request ID;
- HTTP method and path;
- response status;
- direct client socket IP;
- user agent;
- timestamp.

Request bodies, provider credentials, Stripe secrets, and API key plaintext are never written to the audit table.

API key records also track:

- `usage_count`;
- `last_used_at`;
- `last_used_ip`.

The server intentionally uses the direct socket address by default and does not trust `X-Forwarded-For` automatically. If a reverse proxy is introduced, proxy trust should be configured explicitly at the deployment boundary rather than accepting arbitrary forwarded headers.

Operators with `system:read` can query recent tenant events:

```http
GET /api/v1/system/audit?limit=100
X-API-Key: <key with system:read>
```

The Fantastic Admin System Status page displays recent audit events, and the API Keys page shows request count and last client IP.

## Shared Redis rate limiting

Set `REDIS_URL` on API replicas to share rate-limit state:

```env
API_RATE_LIMIT_PER_MINUTE=120
REDIS_URL=redis://redis:6379/0
```

API key plaintext is hashed with SHA-256 before being used as the limiter identity, so Redis keys do not expose credentials.

Redis is the primary limiter in multi-replica deployments. If Redis is temporarily unavailable, the API falls back to the existing process-local limiter instead of failing all requests. Docker Compose now includes Redis 7 and Backend CI executes a real two-instance shared-limit integration test.

## Phase 10 migration

Schema revision `20260924_0004` adds API-key request counters, last client IP, and tenant audit events.

Upgrade existing production databases with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## SaaS human accounts and workspace RBAC

The web console now uses human accounts and short-lived-by-policy session credentials instead of treating a workspace API key as a browser login.

Automation remains separate:

- human browser sessions use `Authorization: Bearer agrs_...`;
- API integrations, MCP and CI continue to use `X-API-Key: agrm_...`;
- session tokens and invitation tokens are stored only as hashes in the database;
- passwords are hashed with Argon2;
- membership is rechecked on every session-authenticated request, so removing a member or changing a role takes effect without waiting for the session to expire.

Default session and invitation policy:

```env
ALLOW_PUBLIC_SIGNUP=true
SESSION_TTL_HOURS=720
INVITATION_TTL_HOURS=168
AUTH_RATE_LIMIT_PER_MINUTE=20
```

Public login and registration are rate-limited by direct client IP. When Redis is configured, this authentication limit is shared across API replicas using a separate `agrm:auth` namespace.

### Workspace roles

Human membership has four roles:

- **Owner** — full workspace access, including ownership and team administration.
- **Admin** — operational administration, billing, API keys, system status and team management; admins cannot create or modify Owner/Admin peers.
- **Analyst** — rank, monitor and geo read/write access plus billing/team visibility.
- **Viewer** — read-only rank, monitor, geo, billing and team visibility.

The last Owner cannot be demoted or removed.

### Account API

Public/session endpoints:

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/switch-workspace`
- `POST /api/v1/auth/accept-invitation`

Team endpoints:

- `GET /api/v1/team/members`
- `GET /api/v1/team/invitations`
- `POST /api/v1/team/invitations`
- `PATCH /api/v1/team/members/{user_id}`
- `DELETE /api/v1/team/members/{user_id}`

Invitations return a plaintext `agri_...` token only when created. The database stores only its SHA-256 hash. The Fantastic Admin Team page turns that one-time token into a shareable `#/login?invite=...` link.

### Migrating an API-key-only workspace

Existing API keys continue to work. A legacy workspace can create its first human Owner with an API key that has `team:manage` (bootstrap `*` keys already qualify):

```http
POST /api/v1/team/bootstrap-owner
X-API-Key: agrm_...
Content-Type: application/json

{
  "email": "owner@example.com",
  "password": "use-a-strong-password",
  "display_name": "Workspace Owner"
}
```

Bootstrap only creates a new account. If the email already belongs to an account, use a normal workspace invitation instead; the bootstrap endpoint will not impersonate or issue a session for an existing user.

### Browser console

The login page now provides:

- email/password sign-in;
- new workspace registration;
- invitation-aware registration/joining;
- a Legacy API Key option for migration compatibility.

Workspace → **Team** provides membership roles, invitation creation, member removal and workspace switching. Workspace API Keys remain available for machine-to-machine use.

### Audit identity

Audit events now distinguish `session` and `api_key` actors and can store the human `user_id` for session-authenticated requests. Request bodies and plaintext credentials remain excluded.

## Phase 11 migration

Schema revision `20260924_0005` adds:

- `users`;
- `workspace_memberships`;
- `user_sessions`;
- `workspace_invitations`;
- human actor fields on `audit_events`.

Upgrade an existing database with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Secure browser sessions

Human browser authentication now uses a host-only HttpOnly session cookie instead of persisting the `agrs_...` session token in `localStorage`.

The browser receives two cookies:

- `agrm_session` — HttpOnly session credential; JavaScript cannot read it.
- `agrm_csrf` — per-session CSRF token; the web client mirrors it into `X-CSRF-Token` on unsafe requests.

The CSRF token is also bound to the server-side session by a SHA-256 hash. Cookie-authenticated `POST`, `PUT`, `PATCH`, and `DELETE` requests are rejected unless the cookie, header, and stored session hash all agree.

Bearer sessions remain accepted for non-browser compatibility, and API keys continue to use `X-API-Key`. CSRF enforcement applies only to cookie-authenticated human sessions.

Recommended production settings:

```env
SESSION_COOKIE_NAME=agrm_session
CSRF_COOKIE_NAME=agrm_csrf
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=lax
```

Use HTTPS whenever `SESSION_COOKIE_SECURE=true`. Local HTTP development keeps the default `false`. The default frontend API base URL is now `http://localhost:8000` so the Vite frontend at `http://localhost:5173` remains same-site for development cookies.

Credentialed CORS is enabled only for configured `CORS_ORIGINS`; do not use wildcard origins with cookie sessions.

### Session management

Human users can inspect and control active sessions:

- `GET /api/v1/auth/sessions`
- `DELETE /api/v1/auth/sessions/{session_id}`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/logout-all`
- `POST /api/v1/auth/change-password`

Session metadata includes creation time, last-seen time, direct client IP and user agent. Password changes keep the current session and revoke every other active session.

The Fantastic Admin console exposes these controls under **Workspace → Account Security**.

## Phase 12 migration

Schema revision `20260925_0006` adds per-session CSRF hashes and device metadata:

- `user_sessions.csrf_hash`
- `user_sessions.created_ip`
- `user_sessions.last_seen_ip`
- `user_sessions.user_agent`

Upgrade existing deployments with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```

Existing Phase 11 browser sessions should sign in again after deployment so the browser receives the new HttpOnly session and CSRF cookies.


## Email verification and account recovery

Phase 13 adds email ownership verification, privacy-safe password recovery, login lockout and user-visible authentication history.

New accounts created through public registration start with an unverified email address. Accounts created from a valid workspace invitation are marked verified because possession of the invitation link proves access to the invited mailbox.

Existing users are backfilled as verified by migration `20260925_0007`, so upgrading an existing deployment does not lock current users out.

Account endpoints:

- `POST /api/v1/auth/verify-email`
- `POST /api/v1/auth/resend-verification`
- `POST /api/v1/auth/forgot-password`
- `POST /api/v1/auth/reset-password`
- `GET /api/v1/auth/security-events`

Verification tokens use an `agrv_...` prefix. Password reset tokens use `agrr_...`. Only SHA-256 hashes are stored in the database. Creating a new token invalidates previous unused tokens of the same type, and a successful verification/reset consumes the token permanently.

Forgot-password always returns the same accepted response whether or not the account exists. This prevents the recovery endpoint from becoming an email-enumeration oracle.

Password reset:

- validates the single-use reset token;
- updates the Argon2 password hash;
- clears failed-login counters and account lock state;
- revokes every active session;
- records a security event.

### Login lockout

Default policy:

```env
LOGIN_MAX_FAILURES=5
LOGIN_LOCK_MINUTES=15
```

Repeated invalid passwords increment a per-user failure counter. Reaching the threshold temporarily locks the account and login responds with HTTP `423 Locked`. A successful login clears the counter. A successful password reset also clears any lock.

Login success, login failure, lockouts, reset requests/completions, registration and email verification are written to `auth_events`. Users can review their own events in **Workspace → Account Security**.

### Email delivery

Development defaults to a console/log email sender. Production can use SMTP:

```env
PUBLIC_WEB_URL=https://app.example.com
EMAIL_VERIFICATION_TTL_HOURS=24
PASSWORD_RESET_TTL_MINUTES=30

SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=no-reply@example.com
SMTP_STARTTLS=true
```

The sender abstraction is intentionally separate from account logic, so a managed provider such as SES, Postmark or Resend can replace SMTP later without changing recovery-token behavior.

Workspace invitations are also delivered through the same sender while the console continues to expose the one-time invitation link for manual sharing.

### Browser flows

The Fantastic Admin frontend now includes:

- **Recover** on the sign-in page;
- `/#/reset-password?token=...`;
- `/#/verify-email?token=...`;
- email verification state and resend control in Account Security;
- recent authentication/security events with result, IP and user agent.

## Phase 13 migration

Schema revision `20260925_0007` adds:

- `users.email_verified_at`;
- `users.failed_login_count`;
- `users.locked_until`;
- `users.last_login_at`;
- `users.last_login_ip`;
- `account_tokens`;
- `auth_events`.

Upgrade with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## TOTP MFA, recovery codes and trusted devices

Phase 14 adds human-account multi-factor authentication without changing machine authentication.

Human browser accounts can enroll a standard TOTP authenticator from **Workspace → Account Security**. The TOTP secret is encrypted at rest with Fernet. Recovery codes are high-entropy one-time codes stored only as SHA-256 hashes.

Password login for an MFA-enabled user is now two-stage:

1. email/password is validated;
2. the API returns a short-lived `agrmfa_...` challenge instead of creating a session;
3. `POST /api/v1/auth/mfa/complete` accepts a TOTP or unused recovery code;
4. only successful second-factor verification creates the normal HttpOnly browser session.

A user may mark the browser as trusted. The trusted-device credential is a separate high-entropy `agrd_...` HttpOnly cookie. The database stores only its hash. Trusted-device bypasses are revoked when the user changes or resets the password, disables MFA, or signs out everywhere.

Default MFA settings:

```env
MFA_ENCRYPTION_KEY=
MFA_ISSUER=Amazon Geo Rank Monitor
MFA_CHALLENGE_MINUTES=5
TRUSTED_DEVICE_DAYS=30
TRUSTED_DEVICE_COOKIE_NAME=agrm_trusted_device
```

When `MFA_ENCRYPTION_KEY` is empty, the service derives the encryption key from `API_KEY_PEPPER` for backward-compatible deployment. Production deployments should set a dedicated, stable `MFA_ENCRYPTION_KEY` and protect it like any other encryption secret. Changing that key without re-enrollment makes existing encrypted TOTP secrets unreadable.

### MFA API

Authenticated account setup endpoints:

- `POST /api/v1/auth/mfa/enroll`
- `POST /api/v1/auth/mfa/enroll/verify`
- `POST /api/v1/auth/mfa/recovery-codes/regenerate`
- `POST /api/v1/auth/mfa/disable`

Password-login second step:

- `POST /api/v1/auth/mfa/complete`

Enrollment requires a verified email address. Recovery codes are returned in plaintext only when MFA is enabled or codes are regenerated. Each recovery code can be consumed once.

### Workspace-required MFA

Workspace Owners can manage the policy through:

- `GET /api/v1/team/security-policy`
- `PATCH /api/v1/team/security-policy`

When `require_mfa=true`:

- human sessions must have completed MFA before any scoped workspace API can be used;
- Account Security remains reachable so a newly invited member can enroll MFA;
- enabling the policy requires every current member to already have MFA enabled;
- future invited members may join, but remain restricted until enrollment is complete;
- a user cannot disable MFA while any workspace membership requires it;
- API keys, MCP and CI integrations remain independent from the human MFA policy.

The Team page shows every member's MFA state and exposes the policy switch to Workspace Owners.

### Session and recovery security

MFA-authenticated sessions record `mfa_authenticated_at`. Workspace switching preserves the current session's MFA-authenticated state. Password reset and password change revoke trusted devices. `logout-all` also revokes trusted-device bypasses.

The login UI accepts either a 6-digit TOTP or a recovery code. A required-MFA session is automatically redirected to **Workspace → Account Security** instead of failing repeatedly on business APIs.

## Phase 14 migration

Schema revision `20260925_0008` adds:

- `tenants.require_mfa`;
- `users.mfa_secret_encrypted`;
- `users.mfa_enabled_at`;
- `users.mfa_last_verified_at`;
- `user_sessions.mfa_authenticated_at`;
- `account_tokens.details`;
- `mfa_recovery_codes`;
- `trusted_devices`.

Upgrade with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Enterprise SSO with OpenID Connect

Phase 15 adds workspace-scoped Enterprise SSO for Google Workspace, Microsoft Entra ID and standards-compatible RS256 OpenID Connect providers.

The browser uses Authorization Code + PKCE. SSO state and nonce values are single-use and short-lived. The backend performs the code exchange, validates the signed ID token, and only then creates the normal HttpOnly application session.

The web frontend never receives the OIDC client secret, PKCE verifier, application session token, or raw ID token.

### OIDC validation

The backend validates:

- discovery issuer equality;
- HTTPS provider endpoints;
- RS256 signature against the provider JWKS;
- `kid`, issuer and audience;
- `azp` when an ID token contains multiple audiences;
- expiration, not-before and issued-at timestamps;
- the per-login nonce;
- a stable OIDC subject (`sub`);
- allowed workspace email domains;
- explicit `email_verified=false` rejection.

Workspace identity bindings are stored by `workspace + issuer + subject`. Email is used for the controlled first bind/JIT decision, not as the permanent external identity key.

### Provider configuration

Workspace Owners configure SSO under **Workspace → Team → Enterprise SSO**.

Google Workspace normally uses:

```text
Provider: Google Workspace
Issuer: https://accounts.google.com
```

Microsoft Entra ID should use the tenant-specific v2.0 issuer rather than a multi-tenant `common` issuer:

```text
https://login.microsoftonline.com/<tenant-id>/v2.0
```

Generic OIDC providers must expose standard discovery at:

```text
<issuer>/.well-known/openid-configuration
```

and currently must sign ID tokens with RS256.

Register the application redirect URI at the identity provider exactly as configured by:

```env
SSO_CALLBACK_URL=https://api.example.com/api/v1/auth/sso/callback
```

The frontend URL is configured separately through `PUBLIC_WEB_URL`; successful callbacks return to `/#/sso-complete`, where the frontend hydrates the already-created HttpOnly application session.

### SSO secret encryption

Recommended production configuration:

```env
SSO_ENCRYPTION_KEY=<stable high-entropy secret>
SSO_CALLBACK_URL=https://api.example.com/api/v1/auth/sso/callback
SSO_TRANSACTION_MINUTES=5
PUBLIC_WEB_URL=https://app.example.com
SESSION_COOKIE_SECURE=true
```

OIDC client secrets and PKCE verifiers are encrypted with Fernet before being stored. If `SSO_ENCRYPTION_KEY` is omitted, the service falls back to `MFA_ENCRYPTION_KEY` and then `API_KEY_PEPPER` for deployment compatibility. Production should use a dedicated stable SSO key.

Do not rotate `SSO_ENCRYPTION_KEY` without a migration/reconfiguration plan; existing encrypted client secrets cannot be decrypted with a different key.

### Safe SSO rollout

SSO rollout intentionally has two stages:

1. save and enable the OIDC connection;
2. use **Test SSO** as a Workspace Owner.

A connection is marked `verified_at` only after a real successful Owner SSO callback. `enforce_sso=true` is rejected until the connection is both enabled and verified.

Changing the issuer, client ID or client secret clears verification and automatically disables enforcement. Changing allowed email domains also disables enforcement so the new access boundary must be reviewed before it is required. Disabling the connection also disables enforcement.

This prevents a mistyped issuer or client credential from immediately locking the workspace out.

### SSO enforcement

When Enterprise SSO is enforced:

- local email/password login is rejected for that workspace;
- an existing local session cannot switch into the workspace;
- every scoped human API request verifies that the current session was issued by that exact workspace's SSO connection;
- an SSO session from Workspace A cannot satisfy Workspace B's SSO requirement;
- API keys, MCP and CI automation remain independent from the human SSO policy.

Existing sessions read the current workspace SSO policy on every authenticated request, so enabling enforcement also protects sessions created before the policy change.

A `team:manage` API key has one deliberately narrow break-glass capability: it may set SSO enforcement to `false`. API keys cannot enable enforcement or change the issuer/client configuration.

### Domain controls and JIT

Each SSO connection has one or more allowed email domains.

With JIT disabled, the OIDC identity must resolve to an existing user who is already a member of the workspace.

With JIT enabled:

- an existing account with an allowed email may be added to the workspace as Viewer;
- an unknown allowed-domain user may be created and joined as Viewer;
- a newly JIT-created SSO user receives an unguessable random local password hash and does not receive a reusable default password.

After first binding, future logins use OIDC issuer + subject rather than relying on the email string.

### SSO and MFA

SSO does not automatically imply MFA.

If the ID token `amr` claim explicitly includes an MFA/OTP/hardware/software-key signal, the application session is marked MFA-authenticated. Otherwise a workspace with `require_mfa=true` requires the user to complete local TOTP/recovery-code verification in **Account Security** before scoped workspace APIs are available.

This allows Workspace Owners to combine:

- IdP-only SSO;
- SSO + local TOTP;
- or IdP-asserted MFA.

### Enterprise SSO API

Public authentication flow:

- `GET /api/v1/auth/sso/discover?email=...`
- `POST /api/v1/auth/sso/start`
- `GET /api/v1/auth/sso/callback`

Authenticated current-session MFA:

- `POST /api/v1/auth/mfa/session-verify`

Workspace Owner controls:

- `GET /api/v1/team/sso-config`
- `PUT /api/v1/team/sso-config`
- `PATCH /api/v1/team/sso-config/enforcement`

Public SSO discovery/start are protected by the authentication IP rate limiter.

## Phase 15 migration

Schema revision `20260925_0009` adds:

- `workspace_sso_configs`;
- `sso_login_transactions`;
- `sso_identities`;
- `user_sessions.auth_method`;
- `user_sessions.sso_owner_id`.

Upgrade with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## SCIM 2.0 provisioning

Phase 16 adds workspace-scoped SCIM 2.0 provisioning for enterprise identity providers.

SCIM complements Enterprise SSO rather than replacing it:

- OIDC SSO controls how human users authenticate.
- SCIM controls user lifecycle, workspace membership state and IdP-driven role assignment.
- API keys, MCP and CI automation remain separate machine-authentication paths.

### Supported SCIM surface

The SCIM base path is:

```text
https://<api-origin>/scim/v2
```

The service supports:

- `GET /ServiceProviderConfig`
- `GET /ResourceTypes`
- `GET /Schemas`
- `GET /Users`
- `POST /Users`
- `GET /Users/{id}`
- `PUT /Users/{id}`
- `PATCH /Users/{id}`
- `DELETE /Users/{id}`
- `GET /Groups`
- `POST /Groups`
- `GET /Groups/{id}`
- `PUT /Groups/{id}`
- `PATCH /Groups/{id}`
- `DELETE /Groups/{id}`

Responses use `application/scim+json`. SCIM errors use the standard
`urn:ietf:params:scim:api:messages:2.0:Error` envelope.

Supported filters include the common provisioning forms:

```text
userName eq "person@example.com"
externalId eq "idp-user-id"
id eq "<scim-resource-id>"
displayName eq "Engineering"
```

Pagination uses `startIndex` and `count`, with a maximum page size of 200.

Bulk and sort are intentionally not advertised as supported.

### Provisioning token

Workspace Owners configure SCIM in **Workspace → Team → SCIM provisioning**.

Generate a provisioning token and configure the IdP with:

```http
Authorization: Bearer agrscim_...
```

The plaintext token is shown once. The database stores only a token prefix and
an HMAC hash. Rotating the token immediately invalidates the previous token.

Recommended production configuration:

```env
SCIM_TOKEN_PEPPER=<independent high-entropy secret>
```

For backward-compatible deployments, `SCIM_TOKEN_PEPPER` falls back to
`API_KEY_PEPPER` when unset. Production should use a dedicated value.

### User lifecycle semantics

A SCIM User maps to one workspace membership, not to the global user identity.

This distinction is deliberate: a person may belong to multiple workspaces.
Deprovisioning from one enterprise must not disable their unrelated workspace
access.

When a SCIM user is deactivated or deleted:

- the workspace membership is marked suspended;
- every active browser session for that user in that workspace is revoked;
- the global user record remains intact;
- memberships and sessions in other workspaces remain untouched;
- normal workspace switching, SSO login and existing-session validation reject
  the suspended membership.

SCIM `DELETE /Users/{id}` therefore behaves as a reversible workspace-level
deprovision operation. Re-provisioning or setting `active=true` can reactivate
the same membership.

SCIM-created users receive a high-entropy random local password hash and their
email is treated as verified for the trusted provisioning flow.

### Stable user identity

The SCIM resource `id` is the workspace membership ID. `externalId` may be
stored per workspace.

`userName` must currently be an email address. Changing `userName` through
SCIM is deliberately rejected because the underlying user identity can be
shared across multiple workspaces. This avoids one enterprise IdP silently
rewriting another workspace's login identity.

### Ownership protection

SCIM can assign only:

- `admin`
- `analyst`
- `viewer`

SCIM can never create, promote, demote or take over a Workspace Owner.
Ownership remains an explicit human administrative boundary.

### Group-driven roles

IdP groups synchronized through `/Groups` appear in the Team SCIM console.
Workspace Owners can map each group to:

- Admin
- Analyst
- Viewer
- no mapping

If a SCIM-managed user belongs to multiple mapped groups, role precedence is:

```text
Admin > Analyst > Viewer
```

If no mapped group applies, the workspace SCIM default role is used. Changing
the default role immediately recomputes SCIM-managed memberships that are not
overridden by a higher mapped-group role.

Manual role controls are disabled in the Team UI for SCIM-managed members to
avoid configuration fights between the application and the identity provider.

### SCIM authentication, rate limiting and audit

SCIM requests use a dedicated Bearer token. They still pass through the normal
API request boundary:

- request IDs are returned in `X-Request-ID`;
- the configured API rate limiter applies;
- rate-limit failures use SCIM error JSON;
- successful authenticated SCIM requests are recorded in the audit log with
  `actor_type=scim`.

### Identity-provider setup

The exact administrator UI varies by identity provider, but the application
side is always:

1. As a Workspace Owner, open **Workspace → Team → SCIM provisioning**.
2. Choose the default workspace role and enable SCIM.
3. Generate or rotate the provisioning token.
4. Configure the IdP provisioning base URL as
   `https://<api-origin>/scim/v2`.
5. Configure the generated Bearer token.
6. Enable user and, if desired, group provisioning in the IdP.
7. After groups synchronize, map IdP groups to workspace roles in the Team page.

The generated token is not stored in browser local storage and cannot be
retrieved again after the one-time display dialog is closed.

### Phase 16 migration

Alembic revision `20260925_0010` adds:

- `workspace_scim_configs`;
- `scim_groups`;
- `scim_group_members`;
- `workspace_memberships.suspended_at`;
- `workspace_memberships.scim_managed`;
- `workspace_memberships.scim_external_id`;
- `workspace_memberships.updated_at`;
- a workspace-scoped unique constraint for SCIM external IDs.

Existing memberships remain active and non-SCIM-managed after migration.

Upgrade with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Rank alerts and notifications

Phase 17 adds proactive ranking alerts on top of completed monitor runs. Alert evaluation happens only after a rank job has reached a successful or partially successful terminal state. Provider retries and failed rank jobs do not emit ranking-change alerts.

Supported rule types:

- `rank_drop`: weighted aggregate rank becomes worse by at least N positions compared with the previous completed run for the same Monitor.
- `rank_improve`: weighted aggregate rank improves by at least N positions.
- `enters_top_n`: weighted rank crosses from below the configured Top N boundary into it.
- `exits_top_n`: weighted rank crosses out of the configured Top N boundary.
- `not_found`: the ASIN has zero aggregate found weight in the current run.
- `geo_not_found`: the ASIN is not found for a matching geographic observation.
- `geo_rank_above`: a geographic observation has an effective rank worse than the configured threshold.

Rules are always evaluated against the same `monitor_target_id`; a run from another Monitor with the same keyword cannot become the comparison baseline.

### Cooldown and deduplication

Each rule has `cooldown_minutes`. Cooldown is scoped to the rule + ASIN + geo + event type, which suppresses repeated identical alerts while allowing unrelated ASINs or geographies to notify independently.

Each emitted event also has a deterministic per-run fingerprint. Re-evaluating the same run cannot create duplicate event rows.

Archiving a rule is a soft delete. Historical alert events and delivery records are retained for incident review and audit.

### Notification channels

A rule may contain one or more of:

- email recipients;
- Slack Incoming Webhook;
- generic HTTPS webhook.

Email uses the same SMTP sender configured for account verification/recovery.

Slack webhook URLs are restricted to official Slack webhook hosts.

Generic webhooks are disabled unless the destination hostname is explicitly present in:

```env
ALERT_WEBHOOK_ALLOWED_HOSTS=alerts.example.com,automation.example.com
```

Private/loopback/link-local IP literal destinations are rejected. For production, network-level egress policy should still restrict worker outbound traffic to the intended notification destinations.

Generic webhooks include:

- `event=rank_alert.triggered`;
- stable `event_id`;
- rule, Monitor and run IDs;
- ASIN and geo;
- previous/current values;
- event details.

The request also carries `X-AGRM-Event-ID` so receivers can implement idempotency.

### Destination secret encryption

Notification channel configuration is encrypted with Fernet before storage. Slack and generic webhook secret URLs are never returned by the API after creation.

Production should configure a dedicated stable key:

```env
ALERT_ENCRYPTION_KEY=<stable high-entropy secret>
ALERT_WEBHOOK_ALLOWED_HOSTS=
```

If `ALERT_ENCRYPTION_KEY` is omitted, the runtime falls back to `MFA_ENCRYPTION_KEY` and then `API_KEY_PEPPER` for deployment compatibility. API and worker processes must use the same effective key.

Do not rotate `ALERT_ENCRYPTION_KEY` without a migration/re-encryption plan; existing channel configuration cannot be decrypted by a different key.

### Delivery failure semantics

Notification delivery is best-effort after the rank job is completed. Email, Slack or webhook failures are stored as `rank_alert_deliveries.status=failed` with a bounded error message.

A notification outage never changes an already completed rank job back to failed/retry. Ranking data remains authoritative even when a downstream notification channel is unavailable.

### Alert API

Read access uses the existing `monitors:read` scope. Rule mutation uses `monitors:write`.

- `GET /api/v1/alerts/rules`
- `POST /api/v1/alerts/rules`
- `PATCH /api/v1/alerts/rules/{rule_id}`
- `DELETE /api/v1/alerts/rules/{rule_id}` (archive)
- `GET /api/v1/alerts/events`

Fantastic Admin exposes **Workspace → Rank Alerts**, including rule configuration, Monitor/ASIN/Geo scoping, cooldown, channel state, alert event history and delivery status. The Monitors screen also links directly into alert creation for a selected Monitor.

## Phase 17 migration

Schema revision `20260925_0011` adds:

- `rank_alert_rules`;
- `rank_alert_events`;
- `rank_alert_deliveries`.

Upgrade with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Historical analytics and scheduled reports

Phase 18 adds monitor-scoped historical analytics, CSV export and scheduled stakeholder email reports.

Analytics are derived directly from completed rank jobs and their existing rank runs, snapshots and geographic observations. The system does not maintain a second analytics copy of ranking results, so the underlying rank run remains the source of truth.

### Historical analytics

Analytics queries are always scoped by both workspace and Monitor. A run belonging to another tenant or another Monitor cannot become part of the same trend even when the keyword or ASIN is identical.

Supported windows are 1 hour through 1 year.

Monitor analytics include:

- weighted aggregate rank history per ASIN;
- first and latest rank in the selected window;
- rank change, where a negative value means improvement;
- best, worst and average weighted rank;
- average confidence;
- aggregate found rate;
- geographic effective-rank averages;
- geographic best/worst rank;
- geographic found rate and observation count.

REST endpoints:

```http
GET /api/v1/analytics/monitors/{monitor_id}/trend?hours=168
GET /api/v1/analytics/monitors/{monitor_id}/summary?hours=168
GET /api/v1/analytics/monitors/{monitor_id}/export.csv?hours=168&granularity=aggregate
GET /api/v1/analytics/monitors/{monitor_id}/export.csv?hours=168&granularity=geo
```

These endpoints require `rank:read`.

The CSV export is generated on demand from the same tenant-scoped historical query used by the UI. Aggregate exports contain weighted snapshots; geographic exports contain individual regional observations.

### Scheduled reports

Workspace administrators can create reports that combine one or more Monitors and deliver a text summary by email. Reports can optionally attach one aggregate CSV file per Monitor.

Each schedule contains:

- report name;
- one or more Monitor IDs;
- recipient email addresses;
- a standard five-field UTC cron expression;
- a lookback window;
- CSV attachment on/off;
- enabled state.

Report schedule configuration and delivery history use `system:read`; creating, changing, archiving or manually sending reports uses `system:write`.

REST endpoints:

```http
GET    /api/v1/reports/schedules
POST   /api/v1/reports/schedules
PATCH  /api/v1/reports/schedules/{schedule_id}
DELETE /api/v1/reports/schedules/{schedule_id}
POST   /api/v1/reports/schedules/{schedule_id}/send
GET    /api/v1/reports/deliveries
```

### Report scheduling semantics

The existing scheduler process dispatches both Monitor rank jobs and scheduled reports.

Like Monitor schedules, reports use five-field cron expressions interpreted in UTC. The scheduler considers only the latest due slot and does not replay every missed historical slot after downtime.

Before sending, the scheduler reserves a `report_deliveries` row. The database unique constraint on `schedule_id + scheduled_for` makes a cron slot idempotent across repeated scans and multiple scheduler replicas.

A delivery records:

- scheduled time;
- status: `sent`, `partially_failed` or `failed`;
- recipient count;
- successful send count;
- subject;
- bounded error text;
- a compact stored rank summary.

One failed recipient does not erase successful recipient deliveries, and report delivery failures never alter underlying rank jobs or rank runs.

### Recipient encryption

Report recipient lists are encrypted with Fernet before storage.

Production should set a stable independent key:

```env
REPORT_ENCRYPTION_KEY=<stable high-entropy secret>
```

If omitted, the runtime falls back to `MFA_ENCRYPTION_KEY` and then `API_KEY_PEPPER` for deployment compatibility.

API and scheduler processes must use the same effective encryption key. Do not rotate `REPORT_ENCRYPTION_KEY` without a migration/re-encryption plan; existing encrypted recipient lists cannot be decrypted with a different key.

The scheduler also requires the same SMTP configuration already used by account emails:

```env
SMTP_HOST=...
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=...
SMTP_STARTTLS=true
```

### Fantastic Admin

The console exposes **Rank Monitoring → Analytics & Reports**.

The page includes:

- Monitor and time-window selection;
- per-ASIN trend sparklines;
- current/change/best/worst/average rank cards;
- geographic performance table;
- aggregate and geographic CSV export;
- Admin report schedule creation/editing;
- manual **Send now**;
- delivery history.

Users without report-management permissions can still use historical analytics and CSV export when they have rank read access.

## Phase 18 migration

Alembic revision `20260925_0012` adds:

- `report_schedules`;
- `report_deliveries`;
- the unique report schedule/slot idempotency constraint.

Existing production databases should run:

```bash
cd backend
alembic -c alembic.ini upgrade head
```


## Billing-aware SERP probe cache

Phase 19 implements the reusable SERP probe cache from the original SaaS design. Cache reuse happens before ASIN matching, because the billable/upstream unit is the SERP probe rather than an individual ASIN.

A cache identity contains the fields that materially affect the upstream SERP:

- tenant / workspace;
- provider mode, provider name and verification level;
- marketplace and keyword;
- requested IP country/state/city/postal code;
- Amazon delivery country/postal code;
- device;
- search depth.

Geo Profile display name, profile ID and weighting are deliberately excluded from the cache identity. This means a weight-only edit can reuse the same compatible SERP and recalculate weighted rank, while an IP location, delivery location, device, search-depth or provider change produces a cache miss.

Cache entries are tenant-scoped and are never shared across workspaces.

### Default cache policy

```env
PROBE_CACHE_MANAGED_TTL_SECONDS=300
PROBE_CACHE_STRICT_TTL_SECONDS=0
PROBE_CACHE_RETENTION_HOURS=24
```

Managed probes reuse a compatible result for five minutes by default. Strict browser verification is uncached by default so an explicit strict verification continues to perform a fresh residential/browser probe. Strict caching can be enabled intentionally by setting a positive strict TTL.

The cache is an optimization rather than a correctness dependency. Cache lookup/store failures fail open and the normal provider path continues.

### Billing behavior

Before a paid request or scheduled worker run, the application preflights fresh compatible cache entries.

Only expected cache misses are included in the credit reservation. After execution, settlement charges only successfully completed upstream probes.

Therefore:

- cache hits do not consume credits as new upstream probes;
- a fully cached request creates no credit reservation;
- a fully cached request can run even when the workspace has zero available credits;
- if another worker fills a cache entry after preflight, the unused reservation is released during settlement;
- provider failures are not converted into cache hits and are not cached.

For rank runs, `settled_probe_count` now explicitly represents successfully completed upstream/billable probes. `cache_hit_count` records reused probes separately.

### Provenance and transparency

Every request still creates a new RankRun and new RankObservation / RankSnapshot rows so historical analytics remain continuous.

Each observation exposes:

- `probe_source=upstream|cache`;
- `cache_age_seconds` for cached observations;
- the original `observed_at` fetch timestamp.

Direct REST/MCP rank-check responses also expose:

```json
{
  "usage": {
    "requested_probe_count": 5,
    "upstream_probe_count": 2,
    "cache_hit_count": 3,
    "billable_probe_count": 2
  }
}
```

Fantastic Admin Rank Explorer and Run History display the same usage/provenance so cache savings are visible rather than implicit.

## Phase 19 migration

Schema revision `20260925_0013` adds:

- `serp_probe_cache`;
- `rank_runs.cache_hit_count`;
- `rank_observations.probe_source`;
- `rank_observations.cache_age_seconds`.

Upgrade existing deployments with:

```bash
cd backend
alembic -c alembic.ini upgrade head
```
