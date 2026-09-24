# API, Worker, Tenant, and MCP Implementation Plan

> **For agentic workers:** Execute task-by-task with TDD. Keep the ranking/provider core reusable and free of transport-specific logic.

**Goal:** Turn the verified ranking engine into an authenticated application service that can be called through FastAPI, persistent monitor jobs, and the official MCP Python SDK v2.

**Base:** `feat/strict-rank-verification` at `0f4343a`.

**Current MCP reference:** official `modelcontextprotocol/python-sdk` v2, using `MCPServer`, `@mcp.tool()`, stdio for local hosts, and Streamable HTTP for deployed servers.

## Constraints

- Billing/Stripe is still out of scope.
- All API/MCP paths call the same application services and ranking engine.
- Tenant ownership is server-side and immutable.
- API keys are never stored plaintext.
- Rank runs become tenant-owned.
- Managed/strict provider choice is explicit.
- Public MCP HTTP must not be deployed unauthenticated. Local stdio may bind to a configured tenant because the launching process is the security boundary.
- No second implementation of ranking logic in routes, worker, or MCP tools.
- Database-backed jobs only; no Redis/Celery yet.

## Task 1 — Execution result + provider registry + tenant-owned rank runs

**Files:**
- Modify domain models
- Modify monitor service
- Modify rank repository/models
- Create application/provider_registry.py
- Tests for execution result, owner_id, managed/strict routing

Required behavior:
- add `RankExecutionResult(run_id,status,snapshots,observations,errors)`
- `check_with_result(request, owner_id=None)`; existing `check()` remains compatible and returns snapshots
- provider registry maps `managed` and `strict`
- strict observations stay STRICT
- rank run stores optional owner_id; SaaS calls always set it

Commit: `feat: add tenant-aware rank application core`

## Task 2 — Tenant, API-key, geo-profile, and monitor persistence

**Files:**
- Extend repository SQLAlchemy models
- Create repositories/tenant_repository.py
- Create repositories/geo_repository.py
- Create repositories/monitor_repository.py
- Create auth/api_keys.py
- Tests

Models:
- tenants
- api_keys
- geo_profiles
- monitor_targets
- monitor_target_asins
- monitor_target_geos

API-key format:
- random `agrm_<token>`
- display prefix stored separately
- HMAC-SHA256 hash with server-side pepper
- plaintext returned only once on creation
- revoked keys fail authentication

Geo profiles and monitors must always be filtered by owner_id.

Commit: `feat: add tenant and monitor persistence`

## Task 3 — Database-backed job queue and worker

**Files:**
- Add rank_jobs SQLAlchemy model
- Create repositories/job_repository.py
- Create workers/rank_worker.py
- Tests

Job fields:
- id
- owner_id
- monitor_target_id nullable
- provider_mode
- request_payload JSON
- pending/running/succeeded/failed
- claimed_at/completed_at
- run_id nullable
- error
- attempt_count

Claiming uses an atomic status transition so two workers cannot both claim one job.

Worker:
- claim one
- reconstruct RankCheckRequest
- get provider from registry
- run tenant-aware RankMonitorService
- complete/fail job

Commit: `feat: add database rank job worker`

## Task 4 — FastAPI application

**Files:**
- Add FastAPI/uvicorn dependencies
- Create api/app.py
- Create api/dependencies.py
- Create api/schemas.py
- Create api/routes/*
- Tests with TestClient/httpx

Endpoints:
- GET /health
- POST/GET /api/v1/geo-profiles
- POST/GET /api/v1/monitors
- GET /api/v1/monitors/{id}
- POST /api/v1/monitors/{id}/run -> enqueue
- GET /api/v1/jobs/{id}
- POST /api/v1/rank/check -> immediate explicit check
- GET /api/v1/runs/{id}
- GET/POST/DELETE /api/v1/api-keys

Auth:
- `X-API-Key` for SaaS REST API
- tenant is resolved only from validated key
- resource IDs from another tenant return 404

Bootstrap/admin tenant creation remains a server/CLI concern, not an unauthenticated public route.

Commit: `feat: expose authenticated rank api`

## Task 5 — Official MCP Python SDK v2

**Files:**
- Add `mcp>=2,<3`
- Create mcp/server.py
- Create mcp/tools.py
- Tests using in-memory MCP client or direct tool-registration contract

Tools:
- check_rank
- list_geo_profiles
- create_monitor
- run_monitor
- get_rank_run
- get_rank_history

Design:
- MCP tools call the same application/repository services as REST.
- Local stdio server binds to `MCP_TENANT_ID`.
- Streamable HTTP app factory is provided but must require an external OAuth 2.1 TokenVerifier/AuthSettings configuration before public deployment.
- Do not pretend an API key is an OAuth token.
- No billing mutation tool.

Commit: `feat: add official mcp v2 rank server`

## Task 6 — Entrypoints, docs, Docker-ready runtime, CI

**Files:**
- backend main/CLI entrypoints
- README
- .env.example
- pyproject scripts
- Dockerfile/compose if needed for backend runtime
- CI remains pytest + Ruff

Document:
- bootstrap tenant/API key
- start REST API
- run one DB worker iteration/loop
- run MCP stdio
- run authenticated Streamable HTTP only after OAuth verifier integration
- managed vs strict mode

Final gates:
- all tests green
- Ruff green
- no plaintext API keys in DB/tests/log fixtures
- cross-tenant lookup tests pass
- MCP tool test proves same rank service is called
- job double-claim test passes
- REST auth test passes
- no Stripe imports

Commit: `docs: document api worker and mcp runtime`
