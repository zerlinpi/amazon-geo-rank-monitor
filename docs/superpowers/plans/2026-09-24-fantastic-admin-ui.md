# Fantastic Admin SaaS UI Implementation Plan

> **For agentic workers:** Execute task-by-task with TDD/build gates. Fantastic Admin Basic v6.4.0 is the authoritative visual and interaction reference.

**Goal:** Deliver a production-buildable SaaS console for Amazon geographic rank monitoring, credits, and API/MCP access, using Fantastic Admin Basic / Element Plus conventions.

**Base:** `feat/credits-stripe` at `e7089d402202e3aebf7cf81d44897107f07b0fb1`.

**Upstream UI reference:** `fantastic-admin/basic` v6.4.0, commit `4cf1d0f92c3c7a8651bc41c6c3b65aabbde30af1`, MIT.

**Tech Stack:** Vue 3.5+, Vite 8, TypeScript, Pinia 4, Vue Router 5, Element Plus 2.14, UnoCSS 66, Axios, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-24-amazon-geo-rank-saas-design.md`

## Global Constraints

- All page types first follow Fantastic Admin Basic patterns.
- Keep a pinned upstream source reference under `frontend/upstream/fantastic-admin`.
- Preserve Fantastic Admin MIT notice in `THIRD_PARTY_NOTICES.md`.
- Do not create a second competing UI system.
- Use existing backend APIs; business ranking logic never moves into frontend.
- API key is V1 console authentication. It is stored in localStorage and sent only as `X-API-Key`.
- Frontend never receives provider credentials, Stripe secret keys, or Stripe Price IDs.
- Local dev uses Vite proxy; production frontend uses Nginx reverse proxy to API.
- Responsive desktop/tablet/mobile behavior is required.

## Task 1 — Pin Fantastic Admin upstream and UI attribution

**Files:**
- Add `.gitmodules`
- Add gitlink `frontend/upstream/fantastic-admin`
- Add `THIRD_PARTY_NOTICES.md`
- Add `docs/superpowers/references/fantastic-admin-ui-map.md`

Reference mapping:
- login -> `apps/core-element-plus/src/views/login.vue`
- shell -> `apps/core-element-plus/src/layouts/index.vue`
- dashboard cards -> `apps/core-element-plus/src/views/index.vue`
- table/form/modal patterns -> core/example Element Plus pages
- global layout vars -> `apps/core-element-plus/src/assets/styles/globals.css`

Gate: pinned commit and MIT attribution are present.

## Task 2 — Backend read APIs required by dashboard/history

**Files:**
- Extend `JobRepository`
- Extend rank/monitor routes
- Add tests

Endpoints:
- `GET /api/v1/runs?limit=50`
- `GET /api/v1/monitors/{id}/history?limit=50`
- `GET /api/v1/jobs?limit=50`

All tenant scoped.

Gate: cross-tenant history cannot be read.

## Task 3 — Frontend scaffold and authentication

**Files:** `frontend/app/**`

Implement:
- Vue/Vite/Element Plus/UnoCSS app
- router + Pinia
- Axios client with `X-API-Key`
- API-key login page adapted from Fantastic Admin login composition
- navigation guard
- logout
- light/dark preference
- global Fantastic Admin-derived layout variables

Gate:
- TypeScript build passes
- auth store tests
- invalid API key stays on login
- valid key enters dashboard

## Task 4 — Fantastic Admin-style application shell

Implement:
- 60px topbar
- collapsible sidebar
- mobile drawer
- page title/breadcrumb area
- credit balance chip
- theme toggle
- logout
- route menu

Menu:
- Dashboard
- Rank Explorer
- Monitors
- Geo Profiles
- Credits & Billing
- API & MCP
- Settings

Gate: routing and responsive shell tests/build pass.

## Task 5 — Rank Explorer and Geo Profiles

Rank Explorer:
- marketplace
- keyword
- multi-ASIN textarea
- geo multi-select
- search depth
- managed/strict mode
- execute rank check
- weighted rank cards
- regional observation table
- found/not-found/error state

Geo Profiles:
- table/search
- create dialog
- separate IP location and Deliver-to location fields
- weight/device
- explicit managed-vs-strict explanation

Gate: input payload and result rendering tests.

## Task 6 — Monitors and history

Monitors:
- searchable Element Plus table
- create monitor drawer/dialog
- run now
- status
- weighted rank/current history

Monitor detail:
- monitor definition
- linked geo profiles
- recent runs
- regional observations per run

Gate: monitor CRUD/read/run UI integration build passes.

## Task 7 — Dashboard

Cards:
- available credits
- reserved credits
- monitor count
- recent run status
- recent probe usage

Sections:
- recent runs
- rank changes / weighted rank summary
- quick rank check
- low-credit warning

Gate: data loading gracefully handles empty accounts/new tenants.

## Task 8 — Credits & Billing

Implement:
- balance/reserved cards
- credit packs
- Stripe Checkout redirect button
- ledger table
- operation type/status formatting
- no Stripe Price ID rendered
- success/cancel feedback based on URL only, followed by server balance refresh

Gate: client cannot submit amount/credits/price ID.

## Task 9 — API & MCP / Settings

API & MCP:
- create/list/revoke API keys
- show plaintext only immediately after creation
- copy control
- local stdio MCP configuration examples
- Streamable HTTP OAuth note

Settings:
- stored UI preferences
- API base diagnostics
- provider capability indicators without secrets

Gate: key hash/secret never rendered.

## Task 10 — Production build, CI, Docker

Add:
- frontend CI with Node 24 + pnpm
- `pnpm lint/typecheck/test/build`
- frontend Dockerfile
- Nginx SPA fallback + reverse proxy to `api:8000`
- Compose frontend service
- README run instructions

Phase gate:
- backend CI green
- frontend CI green
- production build succeeds
- attribution present
- no secrets in bundle
- all primary routes render
