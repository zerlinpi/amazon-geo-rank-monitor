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

- provider-neutral rank core;
- separate IP and Amazon delivery geographies;
- Oxylabs managed adapter;
- strict Playwright + residential proxy verification;
- organic/sponsored separation;
- multi-ASIN matching from one SERP;
- Decimal weighted-rank calculation;
- SQLite-compatible SQLAlchemy persistence;
- rank-run orchestration and partial-failure semantics;
- GitHub Actions tests and Ruff checks.

Next isolated phases are REST/API-key/worker/MCP exposure, prepaid credits/Stripe, and the Fantastic Admin Basic SaaS UI. The complete architecture is documented in `docs/superpowers/specs/2026-09-24-amazon-geo-rank-saas-design.md`.


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
- `POST/GET /api/v1/geo-profiles`
- `POST/GET /api/v1/monitors`
- `GET /api/v1/monitors/{id}`
- `POST /api/v1/monitors/{id}/run`
- `GET /api/v1/jobs/{id}`
- `POST /api/v1/rank/check`
- `GET /api/v1/runs/{id}`
- `GET/POST/DELETE /api/v1/api-keys`

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

SaaS rank jobs are metered by **SERP probe**, not by ASIN. If one Amazon SERP is reused to locate 10 ASINs, it is still one billable probe.

Default rate-card environment variables:

```env
MANAGED_SERP_CREDITS=1
STRICT_SERP_CREDITS=5
```

For example, 3 geographic profiles in managed mode reserve 3 credits even if the monitor contains many ASINs. The worker reserves the maximum probe cost before contacting a provider, settles only successful probes, and releases unused credits.

Credit state is represented by an account cache plus an append-only ledger:

```text
purchase:   available +500, reserved +0
reserve:    available   -3, reserved +3
settle 2:   available   +0, reserved -2
release 1:  available   +1, reserved -1
```

If available credits are insufficient, the rank job fails before Oxylabs or Playwright is called.

### Stripe credit packs

Create one-time Stripe Products/Prices in Stripe, then map those server-owned price IDs to credit packs. No live Price ID is hard-coded in this repository.

Example:

```env
CREDIT_PACKS_JSON=[{"id":"starter","name":"Starter","credits":500,"stripe_price_id":"price_...","display_order":1}]
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_SUCCESS_URL=https://app.example.com/billing/success
STRIPE_CANCEL_URL=https://app.example.com/billing
```

Checkout uses Stripe `mode=payment`. Clients send only a `credit_pack_id`; credit count and Stripe Price ID are reloaded from the server database.

Credits are **not** granted from the Checkout success redirect. They are granted only after a Stripe-signed webhook reports a paid Checkout Session. Duplicate webhook event IDs and duplicate payment grants are idempotent.

Billing endpoints:

- `GET /api/v1/credits`
- `GET /api/v1/credits/ledger`
- `GET /api/v1/billing/packs`
- `POST /api/v1/billing/checkout`
- `POST /api/v1/billing/webhook`

The first four customer-facing operations use tenant authentication where applicable. The webhook endpoint instead authenticates the raw request body with the `Stripe-Signature` header and the configured webhook endpoint secret.
