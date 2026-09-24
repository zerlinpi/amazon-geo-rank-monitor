# Credits and Stripe Prepaid Billing Implementation Plan

> **For agentic workers:** Execute task-by-task with TDD. Billing wraps rank execution at the worker/application boundary; the ranking core remains Stripe-free.

**Goal:** Add prepaid credits, immutable auditable credit movements, reserve→execute→settle usage metering for SERP probes, and Stripe Checkout credit-pack purchases.

**Base:** `feat/api-worker-mcp` at `5eac32404c50a2c5802196f6990437c79fd08b80`.

**Stripe SDK:** `stripe>=15.6,<16`, using `StripeClient` behind a local gateway abstraction.

**Spec:** `docs/superpowers/specs/2026-09-24-amazon-geo-rank-saas-design.md`

## Global Constraints

- Commercial model is prepaid credits; subscriptions are out of scope.
- Billable unit is a SERP probe, never an ASIN.
- One SERP serving multiple ASINs incurs one probe charge.
- Rate card is configurable; managed and strict probes may have different credit costs.
- Credits use integer units; no binary floating point financial state.
- Credit mutations are transactionally reflected in an append-only ledger.
- Every paid mutation has an idempotency key.
- Reserve before provider execution; settle actual successful probes; release unused reservation.
- Insufficient credits prevent provider execution.
- Ranking core/domain/provider modules do not import Stripe.
- Stripe browser redirects never grant credits.
- Stripe webhook signature verification uses the raw request body and endpoint secret.
- Duplicate Stripe event IDs do not duplicate credit grants.
- Checkout price/credit amount comes from server-owned credit-pack data, never request-provided amounts.
- REST webhook is not protected by SaaS `X-API-Key`; Stripe signature is its authentication boundary.
- MCP does not expose ledger mutation or checkout tools in this phase.

## Review Focus

- Retried reserve/settle/release calls with the same idempotency key must not double-mutate balances.
- A job reserving 5 credits and successfully completing 4 probes must consume 4 and return 1 to available balance.
- A provider failure before any successful probe must release the whole reservation.
- A duplicate `checkout.session.completed` webhook must create exactly one grant.
- An unpaid Checkout completion must not grant credits.
- A client must not be able to alter Stripe price ID or number of purchased credits.
- Cross-tenant credit account and ledger access must remain isolated.
- A job with insufficient available credits must make zero provider calls.

---

## Task 1 — Credit ledger, accounts, packs, and reservations

**Files:**
- Extend `backend/src/amazon_geo_rank_monitor/repositories/models.py`
- Create `backend/src/amazon_geo_rank_monitor/billing/__init__.py`
- Create `backend/src/amazon_geo_rank_monitor/billing/rate_card.py`
- Create `backend/src/amazon_geo_rank_monitor/repositories/billing_repository.py`
- Create `backend/tests/test_billing_ledger.py`

**Tables:**

`credit_accounts`
- owner_id primary key
- available_credits integer >= 0
- reserved_credits integer >= 0
- updated_at

`credit_ledger_entries`
- id
- owner_id
- entry_type
- available_delta
- reserved_delta
- idempotency_key unique
- reference_type
- reference_id
- metadata JSON
- created_at

`credit_reservations`
- id
- owner_id
- amount
- settled_amount
- released_amount
- status
- idempotency_key unique
- reference_type
- reference_id
- created_at/completed_at

`credit_packs`
- id
- name
- credits
- stripe_price_id unique
- active
- display_order

**Ledger transitions:**
- purchase 1000 => available +1000, reserved +0
- reserve 5 => available -5, reserved +5
- settle 4 => available +0, reserved -4
- release 1 => available +1, reserved -1

After reserve, total equity remains unchanged. Settlement reduces total equity. Release restores unused held credits.

- [ ] Write failing tests for grant, reserve, insufficient credits, partial settlement, full release, and duplicate idempotency keys.
- [ ] Implement repository methods atomically.
- [ ] Ensure tenant-scoped list/get methods.
- [ ] Run full pytest + Ruff.
- [ ] Commit: `feat: add prepaid credit ledger`

## Task 2 — Rank usage meter and worker integration

**Files:**
- Create `backend/src/amazon_geo_rank_monitor/billing/usage.py`
- Modify `backend/src/amazon_geo_rank_monitor/workers/rank_worker.py`
- Modify `backend/src/amazon_geo_rank_monitor/api/app.py` service container if necessary
- Create `backend/tests/test_rank_billing.py`

**Rate card:**

```python
RateCard(
    managed_serp_credits=1,
    strict_serp_credits=5,
)
```

Required:
- estimated reservation = geo count × rate for provider mode
- ASIN count never affects cost
- reserve before provider execution
- actual successful probe count comes from rank run / execution result
- settle successful probe count × rate
- release unused reservation automatically
- if service raises, release all
- if insufficient credits, fail job with machine-readable `INSUFFICIENT_CREDITS`, no provider call
- Worker remains usable without usage meter for non-SaaS/internal backward compatibility

- [ ] Write failing tests, including 10 ASINs × 3 geos = 3 managed probe charges.
- [ ] Integrate optional usage meter with worker.
- [ ] Run all tests + Ruff.
- [ ] Commit: `feat: meter rank probes with prepaid credits`

## Task 3 — Stripe gateway, payments, and credit packs

**Files:**
- Add `stripe>=15.6,<16` to `backend/pyproject.toml`
- Extend SQLAlchemy models for payments/webhook events
- Create `backend/src/amazon_geo_rank_monitor/billing/stripe_gateway.py`
- Create `backend/src/amazon_geo_rank_monitor/billing/stripe_service.py`
- Extend `billing_repository.py`
- Create `backend/tests/test_stripe_billing.py`

**Tables:**

`payments`
- id
- owner_id
- credit_pack_id
- provider = stripe
- status = created / checkout_created / paid / failed / refunded
- stripe_checkout_session_id unique nullable
- stripe_payment_intent_id nullable
- idempotency_key unique
- created_at/paid_at

`webhook_events`
- provider
- event_id
- event_type
- processed_at
- unique(provider,event_id)

**Checkout:**
- client sends only `credit_pack_id`
- service loads active pack
- Stripe Checkout Session:
  - `mode="payment"`
  - server-owned `price`
  - quantity 1
  - server-owned success/cancel URLs
  - metadata: owner_id, pack_id, payment_id
- explicit Stripe request idempotency key based on payment id
- return session id + URL only

**Webhook:**
- verify signature from raw body + `Stripe-Signature`
- process `checkout.session.completed` only if `payment_status == "paid"`
- also process `checkout.session.async_payment_succeeded`
- event ID idempotency
- payment grant idempotency
- purchase ledger credit amount comes from DB pack, not event metadata
- unpaid completion records event but does not grant

- [ ] Write fake gateway tests before implementation.
- [ ] Implement StripeClient adapter.
- [ ] Run full suite + Ruff.
- [ ] Commit: `feat: add Stripe credit pack checkout`

## Task 4 — Billing REST API

**Files:**
- Create `backend/src/amazon_geo_rank_monitor/api/routes/billing.py`
- Extend `backend/src/amazon_geo_rank_monitor/api/app.py`
- Extend schemas
- Create `backend/tests/test_billing_api.py`

**Authenticated endpoints:**
- `GET /api/v1/credits`
- `GET /api/v1/credits/ledger`
- `GET /api/v1/billing/packs`
- `POST /api/v1/billing/checkout`

**Stripe-authenticated endpoint:**
- `POST /api/v1/billing/webhook`

Requirements:
- credit/account endpoints tenant scoped
- checkout cannot accept amount/price/credits
- webhook uses raw bytes
- missing/invalid Stripe signature => 400
- duplicate event => 200 idempotently
- secret/payment metadata never appears in API responses

- [ ] Write failing FastAPI tests.
- [ ] Implement routes.
- [ ] Run full suite + Ruff.
- [ ] Commit: `feat: expose credits and Stripe billing API`

## Task 5 — SaaS runtime wiring, default packs, docs

**Files:**
- Modify `backend/src/amazon_geo_rank_monitor/config.py`
- Modify `backend/src/amazon_geo_rank_monitor/runtime.py`
- Modify `backend/src/amazon_geo_rank_monitor/main.py`
- Modify `.env.example`
- Modify `compose.yaml`
- Modify `README.md`
- Add tests

**Settings:**
- `MANAGED_SERP_CREDITS=1`
- `STRICT_SERP_CREDITS=5`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_SUCCESS_URL`
- `STRIPE_CANCEL_URL`

Runtime:
- billing ledger available even without Stripe credentials
- checkout route returns configuration error until Stripe is configured
- SaaS worker gets usage meter and therefore requires credits
- CLI/internal worker may explicitly opt out only via a documented internal mode if needed
- bootstrap may optionally seed default pack records without calling Stripe
- actual Stripe price IDs come from env/admin data, never hard-coded fake live IDs

Document:
- creating Stripe Products/Prices externally and inserting pack mappings
- local webhook testing
- balance/reservation semantics
- why redirect does not grant credits
- cost examples by probe count

- [ ] Add runtime tests.
- [ ] Update documentation.
- [ ] Run pytest + Ruff.
- [ ] Commit: `docs: document prepaid credit billing`

## Phase Completion Gate

1. All existing Phase 1-3 tests remain green.
2. Credit ledger tests prove reserve→settle→release arithmetic and idempotency.
3. Job test proves insufficient credits causes zero provider calls.
4. Job test proves ASIN count does not affect credit cost.
5. Stripe checkout is server-priced and `mode=payment`.
6. Stripe webhook signature verification is covered.
7. Duplicate Stripe webhook does not double-grant.
8. Unpaid Checkout completion does not grant.
9. Billing endpoints remain tenant-scoped.
10. Ranking/provider modules import no Stripe.
11. GitHub Backend CI passes pytest and Ruff.
