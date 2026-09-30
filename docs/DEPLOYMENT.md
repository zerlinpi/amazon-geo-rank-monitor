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
API listen address/port and trusted frontend address; migrations run explicitly with
`AUTO_CREATE_SCHEMA=false`.
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
port 8080, forwarding `/api/` and `/scim/v2/` as well as static content. Do not expose DB or Redis
ports. Keep the API's 8000 endpoint private. Terminate HTTPS before accepting
production sessions. Secure cookies will not work over plain HTTP development.

The host TLS proxy must **replace** incoming `X-Forwarded-For` with its socket peer
address (for nginx: `proxy_set_header X-Forwarded-For $remote_addr;`). Do not append
untrusted client-supplied values. Frontend nginx trusts only `TRUSTED_EDGE_PROXY_CIDR`
(default: the dedicated Docker bridge gateway); it replaces the header again before
passing it to API. Uvicorn trusts only `AGRM_FRONTEND_IP` in Compose. Never set either
trust boundary to `*` or `0.0.0.0/0`. Keep ingress loopback-only so a public client
cannot reach a trusted host port directly. If your edge proxy is another container,
give it a fixed address and set that exact address as `TRUSTED_EDGE_PROXY_CIDR`.
If `172.30.91.0/24` overlaps an existing network, change `AGRM_NETWORK_SUBNET`,
`AGRM_NETWORK_GATEWAY`, `AGRM_FRONTEND_IP` and the edge trust address together.
Bare-process deployments use `FORWARDED_ALLOW_IPS` (default `127.0.0.1`) and must
restrict it to their actual reverse proxy. The nginx/Uvicorn default access logs
are disabled, including request-line error logging in the API proxy location;
the application's path-only request log retains request ID and
latency without SSO callback codes, state, cookies or query strings.

CI checks separate client rate-limit buckets through the trusted ingress, rejects
forged forwarding headers at both proxy boundaries, checks SCIM JSON responses and
verifies that callback secrets are absent from container logs both during normal
responses and after deliberately stopping the isolated API container.
The internal proxy connection timeout is 3 seconds, so an unavailable API returns
a gateway error promptly; the 130-second response timeout still allows long reads.

`/health` proves the API process is alive; `/ready` checks DB and configured Redis.
Redis failure makes readiness fail even though request limiting falls back locally.
Check `/api/v1/system/queue` and `/api/v1/system/workers` using an authorized account.
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
