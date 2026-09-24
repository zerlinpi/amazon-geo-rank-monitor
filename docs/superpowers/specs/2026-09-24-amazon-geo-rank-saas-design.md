# Amazon Geo Rank Monitor SaaS — System Design

**Date:** 2026-09-24  
**Repository:** `zerlinpi/amazon-geo-rank-monitor`  
**Status:** Conversational architecture approved; written specification pending user review

## 1. Product Purpose

Build a focused SaaS for Amazon geographic organic-rank monitoring.

A customer provides:

- Amazon marketplace
- keyword
- one or more ASINs
- one or more geographic profiles
- optional monitoring schedule

The service queries Amazon search results across multiple geographic contexts, separates organic from sponsored positions, locates each ASIN, and calculates a weighted organic rank.

The SaaS supports prepaid credits, API keys, REST API access, and MCP access for ChatGPT/other MCP clients.

The project MUST NOT include Amazon Ads bid automation in this repository.

## 2. Success Criteria

A production-ready first release must be able to:

1. Query the same keyword from multiple configured geographic profiles.
2. Model IP location and Amazon delivery location separately.
3. Read organic search results and locate one or more target ASINs.
4. Calculate weighted organic rank deterministically.
5. Store observations and rank history.
6. Use Oxylabs as the primary managed search provider.
7. Support a browser + residential proxy verification provider for strict geographic verification.
8. Expose the same rank service through REST, internal worker jobs, CLI, and official MCP Python SDK v2 tools.
9. Meter actual SERP probes and deduct prepaid credits safely.
10. Provide a SaaS admin/dashboard UI based on Fantastic Admin Basic.
11. Preserve third-party license attribution for any reused Fantastic Admin source.

## 3. Explicit Non-Goals

The first product release does NOT implement:

- Amazon Ads API
- automatic bid or budget changes
- AI bidding
- competitor intelligence beyond ranking ASINs found in the same SERP
- review scraping
- listing optimization
- inventory management
- marketplace repricing
- multi-provider billing abstraction beyond Stripe
- seat-based enterprise billing
- complex subscription tiers

The core business capability is Amazon geographic rank monitoring.

## 4. Reference Projects and Adopted Lessons

### Amazon rank/scraping references

- `Lumen-Ads/amazon-sp-rank-tracker`: useful separation of scraper-related responsibilities; desktop UI / Excel / Selenium coupling is intentionally rejected.
- `luminati-io/Amazon-scraper`: useful Amazon SERP extraction and geo-scraping patterns.
- `phoenine/amazon-scraper`: useful Playwright, retry, job state, cache, and anti-bot patterns.
- `oxylabs/oxylabs-sdk-python`: primary integration reference for `amazon.scrape_search`, parsed organic results, realtime/async integration, and managed geo requests.

### MCP references

- `modelcontextprotocol/python-sdk`: official MCP Python SDK v2 is the only MCP protocol implementation.
- `redhat-data-and-ai/template-mcp-server`: reference for production configuration, health checks, transport, structured logging, tests, and container deployment.

### Billing references

- `Zonastery/bursar`: reference for immutable credit ledger, idempotency, and reserve-then-settle accounting.
- `ToseaAI/stripe-entitlements`: reference for verified Stripe webhook projection and credit-pack flows.
- `Anujakhatri/Metering-Billing-Engine`: reference for idempotent metering and quota/usage separation.

### UI reference

- `fantastic-admin/basic`: authoritative UI implementation reference.
- License: MIT.
- Frontend baseline: `apps/core-element-plus`.
- Examples may be adapted from `apps/example/src/views`.
- Reused source MUST retain required MIT copyright/license notice.

## 5. Architecture Overview

```text
Web UI / REST API / MCP / CLI
            |
            v
      Application Layer
  Auth / API Keys / Credits
            |
            v
       Rank Service
            |
      Geo Orchestrator
            |
   +--------+---------+
   |                  |
   v                  v
Oxylabs Provider   Browser Verification Provider
   |                  |
   +--------+---------+
            |
            v
      SERP Normalizer
            |
            v
        ASIN Matcher
            |
            v
      Weighted Rank
            |
            v
       Persistence
```

The rank core must not depend on Stripe, web UI, or MCP.

MCP, REST, CLI, and the worker all call the same application service.

## 6. Recommended Repository Shape

```text
amazon-geo-rank-monitor/
├── backend/
│   ├── pyproject.toml
│   ├── src/amazon_geo_rank_monitor/
│   │   ├── domain/
│   │   ├── providers/
│   │   ├── geo/
│   │   ├── ranking/
│   │   ├── monitor/
│   │   ├── billing/
│   │   ├── repositories/
│   │   ├── api/
│   │   ├── mcp/
│   │   ├── workers/
│   │   ├── config.py
│   │   └── main.py
│   └── tests/
├── frontend/
│   ├── app/
│   └── upstream/
│       └── fantastic-admin/
├── config/
│   ├── geo_profiles.example.yaml
│   └── rate_card.example.yaml
├── docs/
│   └── superpowers/
│       ├── specs/
│       └── plans/
├── compose.yaml
├── .env.example
├── THIRD_PARTY_NOTICES.md
└── README.md
```

### Frontend source strategy

Fantastic Admin Basic is treated as a pinned upstream UI foundation.

Implementation should prefer one of these mechanisms in this order:

1. pinned vendored snapshot or subtree of the required Fantastic Admin Basic source;
2. pinned git submodule if vendoring becomes operationally impractical;
3. direct adaptation of only the required MIT-licensed files.

The implementation plan must choose one concrete mechanism and pin an upstream commit/release.

Do not independently recreate Fantastic Admin components that already exist upstream.

## 7. Frontend UI Standard

All SaaS UI types use Fantastic Admin Basic / Element Plus conventions.

Primary pages:

- Login / registration
- Dashboard
- Rank Explorer
- Monitors
- Monitor detail
- Geo Profiles
- Run history
- Credits & Billing
- API Keys
- MCP setup
- Settings

### Dashboard

Show:

- credit balance
- active monitors
- SERP probes today
- successful / failed probes
- largest weighted-rank changes
- recent monitor runs

### Rank Explorer

Inputs:

- marketplace
- keyword
- ASIN list
- geo-profile selection
- device
- search depth
- managed vs strict verify mode

Output:

- weighted organic rank
- region-by-region rank
- found/not-found state
- provider
- verification level
- observed timestamp

### Monitor list

Use Fantastic Admin table/search/filter patterns.

Columns:

- monitor name
- marketplace
- keyword
- ASIN count
- geographic-profile count
- weighted rank
- previous rank
- schedule
- status
- last run
- credit cost

### Monitor detail

Use cards + table + trend visualization.

Must show raw regional observations separately from weighted rank.

### Geo Profiles

Each profile stores IP location and delivery location independently.

### Credits & Billing

Use ledger-style transaction table rather than exposing only a mutable balance.

### API / MCP

Show API key management and MCP connection instructions without ever displaying provider credentials.

## 8. Domain Model

### GeoProfile

```text
id
name
marketplace
ip_country
ip_state
ip_city
ip_postal_code
delivery_country
delivery_postal_code
device
weight
enabled
```

IP location and delivery location are deliberately separate fields.

### MonitorTarget

```text
id
owner_id
name
marketplace
keyword
search_depth
schedule
provider_policy
enabled
```

### MonitorTargetASIN

```text
monitor_target_id
asin
label
```

Multiple ASINs may share one SERP probe.

### RankRun

```text
id
monitor_target_id
status
started_at
completed_at
requested_probe_count
settled_probe_count
credits_reserved
credits_settled
```

### RankObservation

```text
id
rank_run_id
geo_profile_id
asin
provider
verification_level
found
organic_rank
absolute_rank
sponsored_rank
effective_rank
page
observed_at
raw_result_reference
error_code
```

### RankSnapshot

```text
id
rank_run_id
asin
weighted_rank
found_weight
missing_weight
confidence
created_at
```

## 9. SERP Probe Identity and Caching

The fundamental data-collection unit is a SERP probe, not an ASIN.

Probe identity:

```text
marketplace
keyword
geo_profile
device
search_depth
provider_mode
```

One SERP response is matched against all ASINs attached to the monitor.

This is required to prevent duplicate provider cost and duplicate customer billing.

A reusable cache may serve identical compatible probes within a configured freshness window.

Cache reuse must be visible in usage metadata and must not charge the customer as if a new upstream probe occurred unless the pricing policy explicitly says otherwise.

## 10. Provider Interface

```python
class RankProvider(Protocol):
    async def search(
        self,
        *,
        marketplace: str,
        keyword: str,
        geo_profile: GeoProfile,
        device: str,
        search_depth: int,
    ) -> SerpResult:
        ...
```

Implementations:

- `OxylabsRankProvider`
- `BrowserVerificationProvider`

Future providers may be added without changing matcher, weighting, billing, MCP, or frontend behavior.

## 11. Hybrid Provider Policy

### Managed mode

Default mode.

Use Oxylabs Amazon Search with parsed output.

Suitable for:

- scheduled monitoring
- bulk runs
- inexpensive routine measurements

### Strict verification mode

Use Playwright through a residential proxy configured for the requested IP geography, then set Amazon Deliver-to independently.

Suitable for:

- manual verification
- large unexpected rank movement
- managed-provider anomaly
- low-confidence observations

Strict verification must record:

- requested IP geography
- verified proxy geography when available
- requested Amazon delivery postal code
- actual delivery state confirmed in browser when detectable

A strict-verification failure does not overwrite a successful managed observation.

## 12. SERP Normalization

Provider-specific responses are normalized into a provider-neutral shape.

```text
SerpResult
- organic_products[]
- sponsored_products[]
- absolute_products[]
- page metadata
- provider metadata
- geo metadata
```

Each product should contain at least:

```text
asin
position
page
sponsored
title (optional)
```

Provider-specific JSON must not leak into weighting logic.

## 13. Rank Matching

For each requested ASIN:

- search normalized organic results
- `organic_rank` is its rank among organic products
- `absolute_rank` is its observed product position including sponsored placements
- `sponsored_rank` is set only when it appears in sponsored results

If the ASIN is not found within `search_depth`:

```text
found = false
organic_rank = null
effective_rank = search_depth + 1
```

Never encode "not found" as rank 0.

## 14. Weighted Rank

Only effective organic rank participates in the weighted score.

```text
weighted_rank =
sum(effective_rank_i * normalized_weight_i)
/
sum(normalized_weight_i)
```

Weights may be supplied as 30/40/30 or 0.3/0.4/0.3; they are normalized internally.

The result must retain both:

- weighted rank
- regional observations

Weighted rank must never replace raw regional evidence.

## 15. Confidence

Initial confidence is deterministic and explanatory, not AI-generated.

Inputs may include:

- share of total geo weight with valid observations
- managed vs strict verification
- provider errors
- disagreement between recent compatible observations
- missing ASIN share

Low confidence must be surfaced to REST/MCP/UI.

No automatic provider escalation is required for the first implementation unless explicitly enabled.

## 16. Storage

### Development

SQLite is supported for local development and tests.

### SaaS production

PostgreSQL is required for:

- concurrent workers
- billing ledger
- Stripe webhook idempotency
- production multi-user operation

All database access uses SQLAlchemy and migrations.

Switching `DATABASE_URL` must not change domain behavior.

## 17. Background Job Model

Do not introduce Redis/Celery in the first release unless proven necessary.

Use a database-backed job queue with:

- pending
- running
- succeeded
- partially_succeeded
- failed
- cancelled

Workers claim jobs transactionally.

The abstraction must permit replacing the queue backend later.

## 18. Billing Model

Commercial model: prepaid credits.

The billable unit is an actual SERP probe.

Do not charge separately for each ASIN found in the same SERP.

Example configurable rate card:

```yaml
operations:
  managed_serp:
    credits: 1
  browser_verified_serp:
    credits: 5
```

Rates are configuration/data, not hard-coded business logic.

## 19. Credit Accounting

Never implement billing as only:

```text
user.balance -= n
```

Use:

- `credit_accounts`
- `credit_ledger_entries`
- `credit_reservations`
- `payments`
- `webhook_events`

Every financial mutation requires an idempotency key.

Ledger entries are append-only for normal operation.

Example entry types:

- purchase
- promotional_grant
- reservation
- settlement
- release
- refund
- manual_adjustment

Use fixed-precision decimal/integer atoms; do not use binary float for financial state.

## 20. Reserve → Execute → Settle

Before a paid rank run:

1. estimate maximum probe cost
2. reserve sufficient credits atomically
3. run probes
4. settle only billable completed probes
5. release unused reservation

Example:

```text
5 managed probes estimated
reserve 5 credits

4 successful upstream probes
1 failed before billable completion

settle 4
release 1
```

Retrying the same job must not double-charge.

## 21. Stripe

Stripe is used for purchasing credit packs.

First release does not require subscriptions.

Flow:

```text
customer -> Stripe Checkout -> payment success
                              |
                              v
                    verified Stripe webhook
                              |
                              v
                    idempotent ledger credit
```

Browser redirect is never proof of payment.

Credit grants occur only after verified server-side webhook processing.

Refund/dispute support must be represented in the data model even if full automation is staged after initial checkout support.

## 22. Authentication and Tenant Boundary

All customer-owned records require an immutable owner/tenant identifier.

Do not use email address as the primary ownership key.

API keys are stored hashed, with:

- prefix for identification
- hash
- owner
- scopes
- created_at
- last_used_at
- revoked_at

Provider credentials and Stripe secrets must only exist server-side.

## 23. REST API Surface

Initial endpoints:

```text
POST /api/v1/rank/check
POST /api/v1/monitors
GET  /api/v1/monitors
GET  /api/v1/monitors/{id}
POST /api/v1/monitors/{id}/run
GET  /api/v1/monitors/{id}/history

GET  /api/v1/geo-profiles
POST /api/v1/geo-profiles

GET  /api/v1/credits
GET  /api/v1/credits/ledger
POST /api/v1/billing/checkout
POST /api/v1/billing/webhook

GET  /api/v1/api-keys
POST /api/v1/api-keys
DELETE /api/v1/api-keys/{id}
```

The API returns structured errors with stable machine-readable codes.

## 24. MCP Surface

Use official MCP Python SDK v2.

Initial tools:

- `check_rank`
- `create_monitor`
- `run_monitor`
- `get_weighted_rank`
- `get_rank_history`
- `list_geo_profiles`
- `verify_rank`
- `get_credit_balance`

MCP tools call the same application services as REST.

MCP must not expose:

- Oxylabs credentials
- residential proxy credentials
- Stripe secrets
- raw credit-ledger mutation tools
- unrestricted admin operations

Transport target for deployed use: Streamable HTTP.

Local developer transport may also support stdio.

## 25. Observability and Audit

Every rank run records:

- request identity
- owner
- monitor
- provider
- geographic profile
- upstream request status
- timing
- result status
- credit reservation/settlement linkage

Logs must not contain secrets.

Billing changes and rank runs require durable audit correlation IDs.

## 26. Error Semantics

Distinguish:

- `SUCCESS_FOUND`
- `SUCCESS_NOT_FOUND`
- `UPSTREAM_TIMEOUT`
- `UPSTREAM_RATE_LIMITED`
- `UPSTREAM_BLOCKED`
- `PARSER_FAILED`
- `GEO_VERIFICATION_FAILED`
- `INSUFFICIENT_CREDITS`
- `RESERVATION_FAILED`

Provider failure must never be converted into "ASIN not found."

## 27. Security Requirements

- secrets from environment/secret manager only
- no secrets committed to git
- Stripe webhook signature verification
- API-key hashing
- rate limiting at public API boundary
- server-side authorization on every tenant resource
- idempotency keys on paid mutations
- browser/proxy credentials isolated from frontend
- raw upstream HTML/JSON retention configurable and disabled by default for unnecessary data

## 28. Testing Strategy

### Unit tests

- weight normalization
- weighted-rank calculation
- not-found effective rank
- multi-ASIN matching from one SERP
- sponsored vs organic separation
- provider-response normalization
- credit reserve/settle/release
- idempotency
- API-key hashing/authorization

### Provider contract tests

Each provider must pass the same normalized-result contract suite using fixtures.

### Integration tests

- SQLite local repository
- PostgreSQL production repository
- REST rank flow
- MCP tool calling application service
- worker claims and completes job
- Stripe signed-webhook projection in test mode
- duplicate webhook idempotency

### Frontend tests

Use Fantastic Admin conventions and verify:

- routing/auth guard
- monitor create/edit flow
- rank table rendering
- credit balance and ledger
- API/MCP instructions

## 29. UI Implementation Constraint

All frontend page types must begin by checking for an equivalent Fantastic Admin Basic implementation.

Examples:

- app shell/navigation: Fantastic Admin core layout
- tables: Element Plus + Fantastic Admin table/page patterns
- forms: Element Plus forms using upstream validation conventions
- auth screens: adapt Fantastic Admin example login structure
- settings: reuse Fantastic Admin settings/layout patterns
- themes/navigation: retain upstream mechanisms where practical

Custom CSS/components are allowed only when no appropriate upstream implementation exists or the product-specific visualization requires it.

Do not introduce a second competing design system.

## 30. Third-Party Licensing

Fantastic Admin Basic is MIT licensed.

If source is copied, vendored, subtree-imported, or substantially adapted:

- preserve its MIT license text
- preserve required copyright notice
- document source and pinned upstream revision in `THIRD_PARTY_NOTICES.md`

Other dependencies retain their respective licenses.

## 31. Implementation Phases

### Phase 1 — Rank Core

Deliver:

- domain models
- geo profiles
- provider abstraction
- Oxylabs provider
- SERP normalizer
- ASIN matcher
- weighted rank
- persistence
- rank history
- tests

### Phase 2 — Strict Verification

Deliver:

- Playwright verification provider
- residential proxy configuration
- delivery-location setting
- geo verification metadata
- strict verification API/service

### Phase 3 — API, Worker, MCP

Deliver:

- FastAPI
- database-backed worker
- official MCP v2 server
- API keys
- rank-run orchestration

### Phase 4 — SaaS Credits & Stripe

Deliver:

- credit ledger
- reservation/settlement
- rate card
- Stripe Checkout
- verified webhooks
- billing APIs

### Phase 5 — Fantastic Admin UI

Deliver:

- pinned Fantastic Admin Basic frontend baseline
- auth
- dashboard
- explorer
- monitors
- geo profiles
- history
- billing
- API/MCP setup
- third-party notices

## 32. Acceptance Example

Input:

```json
{
  "marketplace": "amazon.com",
  "keyword": "walking pad",
  "asins": ["B0AAAA1111", "B0BBBB2222"],
  "geo_profiles": [
    {
      "id": "us-ny-10001",
      "ip_postal_code": "10001",
      "delivery_postal_code": "10001",
      "weight": 30
    },
    {
      "id": "us-ca-90001",
      "ip_postal_code": "90001",
      "delivery_postal_code": "90001",
      "weight": 40
    },
    {
      "id": "us-tx-75201",
      "ip_postal_code": "75201",
      "delivery_postal_code": "75201",
      "weight": 30
    }
  ]
}
```

Expected characteristics:

- exactly three compatible managed SERP probes, not six ASIN-specific probes
- each probe is matched against both ASINs
- regional organic ranks are persisted
- weighted rank is calculated per ASIN
- provider errors remain errors, not not-found observations
- credits are reserved and settled by actual billable probe
- the result is accessible from REST and MCP
- UI renders the same underlying result without duplicating ranking logic

## 33. Architectural Invariants

1. Ranking core never imports Stripe.
2. Billing never parses Amazon SERPs.
3. UI never directly calls Oxylabs or residential proxies.
4. MCP never implements independent ranking logic.
5. One compatible SERP may serve multiple ASINs.
6. Not-found is never rank zero.
7. Provider failure is never not-found.
8. Weighted rank uses organic rank only.
9. IP geography and delivery geography remain separate.
10. Financial mutations are idempotent and ledger-backed.
11. Production SaaS uses PostgreSQL.
12. Fantastic Admin Basic is the single UI foundation.
