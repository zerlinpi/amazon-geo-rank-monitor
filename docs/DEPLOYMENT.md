# Deployment

Use Linux, Docker Engine and Docker Compose v2.24+ (optional `env_file` syntax),
PostgreSQL 17 and Redis 7. CI builds the actual images and starts the entire stack.
Local SQLite remains useful for development; use PostgreSQL for multiple workers.

## Configure

1. Check out the exact reviewed commit. Copy `.env.example` to `.env` and restrict
   permissions (`chmod 600 .env`). Never commit it or upload it as a CI artifact.
2. Set unique `API_KEY_PEPPER` and `POSTGRES_PASSWORD` (at least 32 random bytes;
   hex encoding avoids URL escaping in the Compose database URL). Configure
   dedicated MFA/SSO/alert/report encryption secrets and SCIM pepper. Back up
   these secrets separately before storing encrypted data; losing them loses access.
3. Set `PUBLIC_WEB_URL=https://rank.example.com`, `CORS_ORIGINS=https://rank.example.com`,
   `SESSION_COOKIE_SECURE=true`, `SESSION_COOKIE_SAMESITE=lax`, and
   `SSO_CALLBACK_URL=https://rank.example.com/api/v1/auth/sso/callback`.
   Use exact origins, never a wildcard with credentialed browser sessions.
   Set Stripe return URLs to the public billing page (hash routes where applicable).
4. Configure SMTP host/port/from/login and STARTTLS. Console delivery does not send
   email; verification, recovery, invitations, alerts and reports need working SMTP.
   Confirm delivery in an isolated test account before opening public signup.
5. Set provider credentials only when enabling live collection. Managed Oxylabs
   requires `OXYLABS_USERNAME/PASSWORD`; strict probes require the residential
   proxy settings and independently verify both IP and Amazon Deliver-to location.
   Keep `AUTO_STRICT_VERIFICATION_ENABLED=false` until budgets and geography have
   been checked. Configure credit pack amounts before enabling Stripe checkout.
6. Set `ALLOW_PUBLIC_SIGNUP=false` when onboarding is invitation-only. Register the
   first owner during a controlled initial window before disabling public signup.
   The bootstrap CLI creates a machine API key, not a human session.

Compose reads the same `.env` for API, worker, scheduler and migration, preventing
policy, billing and encryption drift. It overrides DB connection, schema creation,
API listen address and port; migrations run explicitly with `AUTO_CREATE_SCHEMA=false`.
`POSTGRES_PASSWORD` is Compose-only. `VITE_AGRM_*` are build-time frontend values;
the frontend image always uses `/` for API requests through its same-origin proxy.
If changing the CSRF cookie name, rebuild with the matching frontend configuration.

## Start and verify

```sh
docker compose config --quiet
docker compose build
docker compose up -d --wait --wait-timeout 180
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
curl --fail http://127.0.0.1:8080/ --output /dev/null
docker compose exec -T api alembic current
docker compose exec -T worker python -m amazon_geo_rank_monitor.operations.health rank
docker compose exec -T scheduler python -m amazon_geo_rank_monitor.operations.health scheduler
```

The migration service waits for PostgreSQL; API waits for migration and Redis;
worker/scheduler wait for migration; frontend waits for API readiness. Compose
publishes ports only to loopback. Put a TLS reverse proxy in front of frontend
port 8080, forwarding `/api/` as well as static content. Do not expose DB or Redis
ports. Keep the API's 8000 endpoint private. Terminate HTTPS before accepting
production sessions. Secure cookies will not work over plain HTTP development.

`/health` proves the API process is alive; `/ready` checks DB and configured Redis.
Redis failure makes readiness fail even though request limiting falls back locally.
Check `/api/v1/system/status` using an authorized account for queue/worker state.
Set unique worker/scheduler IDs per replica; the default Compose service is one
instance of each. Monitor stale heartbeats, queue age, retries/dead letters, provider
failures, latency and credit reservations. Alert outside this application when it
cannot serve requests. Request logs contain method/path/status/request ID/duration;
provider errors retain error categories rather than potentially secret SDK messages.

## Local checks and network-free E2E

```sh
python -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.lock
.venv/bin/pip install --no-deps -e backend
(cd backend && ../.venv/bin/python -m pytest -q && ../.venv/bin/ruff check src tests)
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run typecheck
VITE_AGRM_API_BASEURL=http://127.0.0.1:8000 npm --prefix frontend run build
(cd frontend && npx playwright install chromium)
npm --prefix frontend run test:e2e
```

E2E runs a temporary SQLite-backed API and real worker on loopback with fake SERP
providers; it never calls paid Oxylabs, residential proxy, Stripe, email or webhook
services. CI uses runner-installed Chrome via Playwright (`E2E_BROWSER_CHANNEL=chrome`).
`E2E_BROWSER_PATH` supports another local Chrome executable. Screenshots on failure
contain only test accounts. Traces are disabled to avoid recording session cookies.
For PostgreSQL tests, `POSTGRES_TEST_URL` must be a disposable dedicated test DB:
legacy tests reset its tables and hardening tests create/drop uniquely named sibling
DBs. Never point it at production. `REDIS_TEST_URL` must use a disposable DB (tests flush it).
