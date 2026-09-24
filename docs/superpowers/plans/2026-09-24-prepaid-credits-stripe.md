# Prepaid Credits and Stripe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development. Steps use checkbox syntax.

**Goal:** Add prepaid SaaS credits, reserve/settle billing for SERP probes, Stripe Checkout credit-pack purchases, verified idempotent webhooks, billing REST endpoints, and MCP balance visibility.

**Architecture:** Billing is isolated in `billing/` plus a repository. The credit ledger is append-only; account balance/reserved counters are transactional projections. Rank execution reserves credits before provider work and settles only successful probes. Stripe only purchases credit packs; internal SERP credits remain application units rather than Stripe monetary billing credits.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, FastAPI, Stripe Python SDK, pytest, existing worker/API/MCP stack.

**Spec:** `docs/superpowers/specs/2026-09-24-amazon-geo-rank-saas-design.md`

## Global Constraints

- Bill by actual SERP probe, not ASIN count.
- Managed and strict rates are configurable data.
- Financial mutations require idempotency keys.
- Ledger entries are append-only.
- Reserve before execution; settle successful probes; release unused reserve.
- No subscription billing in this phase.
- Checkout success redirect never grants credits.
- Only verified Stripe webhook processing grants purchased credits.
- Stripe/provider secrets never reach frontend/MCP payloads.
- Existing rank semantics and provider behavior must remain unchanged.

## Review Focus

- Retried reservation with same idempotency key must not reserve twice.
- Duplicate Stripe webhook must not grant credits twice.
- Insufficient available balance must fail before provider calls.
- Partial rank success settles only successful probe cost and releases the remainder.
- Worker failure before successful probes releases the reservation.

### Task 1: Billing tables and transactional ledger repository
Create billing/account/reservation/payment/webhook SQLAlchemy rows and `BillingRepository`.
Tests cover grant, reserve, insufficient balance, settle+release, idempotency, and append-only ledger.

### Task 2: Rate card and billed rank execution
Create `RateCard` and billing application service.
Managed default = 1 credit/probe; strict default = 5 credits/probe.
Integrate synchronous rank execution and worker execution with reserve → execute → settle/release.

### Task 3: Stripe Checkout and verified webhook
Add Stripe dependency/configuration, credit packs, checkout session creation, signature verification, completed-session projection, duplicate-event protection, and payment records.
Webhook metadata includes tenant_id + credit_pack_id; amount/credits are reloaded server-side from stored pack.

### Task 4: Billing REST and MCP surfaces
Add:
- GET /api/v1/credits
- GET /api/v1/credits/ledger
- GET /api/v1/billing/packs
- POST /api/v1/billing/checkout
- POST /api/v1/billing/webhook
- MCP get_credit_balance
Stripe webhook is unauthenticated by API key but signature-verified.

### Task 5: Runtime/docs/CI
Wire BillingRepository/Stripe service into AppServices/runtime, update env/example README, add tests, run pytest + ruff, and create stacked Draft PR.

## Phase Completion Gate

- All previous tests remain green.
- Double reservation/webhook tests pass.
- Provider is not called when credits are insufficient.
- Partial success settles actual successful probes only.
- No credit grant occurs from redirect handling.
- CI pytest + Ruff pass.
