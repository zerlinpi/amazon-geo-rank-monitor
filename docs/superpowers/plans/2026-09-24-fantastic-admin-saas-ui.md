# Fantastic Admin SaaS UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Frontend changes must build against the pinned upstream revision before completion.

**Goal:** Deliver an operational SaaS console for Amazon Geo Rank Monitor using Fantastic Admin Basic / core-element-plus as the single UI foundation.

**Upstream:** fantastic-admin/basic v6.4.0, commit `4cf1d0f92c3c7a8651bc41c6c3b65aabbde30af1`.

**Architecture:** The repository stores product-specific overlay files, not a forked copy of the entire Fantastic Admin monorepo. A sync script clones the pinned upstream into `frontend/.vendor/fantastic-admin`, overlays files from `frontend/overlays`, then runs the upstream core-element-plus build. This preserves upstream layouts/themes/components and keeps provenance explicit.

**Pages:** API-key Login, Dashboard, Rank Explorer, Monitors, Geo Profiles, Run History, Credits & Billing, API Keys, MCP Setup.

**Backend additions:** list rank runs endpoint and optional CORS configuration for local/decoupled frontend deployment.

**Constraints:**
- No second design system.
- Prefer Fantastic Admin shell, routing, theme, menus, Fa components and Element Plus.
- Workspace API Key is the Phase-5 login credential because the current backend has no password-user model.
- Never expose Oxylabs, residential proxy, Stripe secret, or ledger-mutation credentials.
- Payment redirect does not grant credits.
- Fantastic Admin MIT notice and pinned revision must be retained.

## Tasks

1. Pin upstream, add sync/build scripts, third-party notices, and frontend CI.
2. Overlay account store, API client, API-key login and product routes.
3. Implement Dashboard + Rank Explorer.
4. Implement Monitors + Geo Profiles + Run History.
5. Implement Credits/Billing + API Keys + MCP Setup.
6. Add backend run-list endpoint and local CORS configuration.
7. Run pinned upstream TypeScript/Vite production build and backend CI.
8. Create stacked Draft PR on `feat/prepaid-credits-stripe`.
