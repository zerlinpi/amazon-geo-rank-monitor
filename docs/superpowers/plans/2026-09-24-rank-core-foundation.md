# Rank Core Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider-neutral Amazon geographic ranking core that can query managed Amazon SERPs for multiple geo profiles, match multiple ASINs from each shared SERP, calculate weighted organic rank, and persist run history.

**Architecture:** A pure Python domain layer defines geo profiles, normalized SERP products, observations, and snapshots. A provider protocol isolates Oxylabs from ranking logic; `RankMonitorService` performs one provider probe per compatible geo context and fans that result out to all requested ASINs. SQLAlchemy repositories persist runs, observations, and snapshots in SQLite locally and remain database-URL compatible with PostgreSQL later.

**Tech Stack:** Python 3.12+, Pydantic 2, SQLAlchemy 2, httpx, Oxylabs Python SDK, PyYAML, pytest, pytest-asyncio, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-24-amazon-geo-rank-saas-design.md`

## Global Constraints

- Amazon Ads automation is out of scope.
- Oxylabs is the primary managed provider.
- IP geography and Amazon delivery geography are separate domain fields.
- One compatible SERP probe must serve all ASINs attached to that request.
- Weighted rank uses organic rank only.
- Not-found is represented with `organic_rank=None` and `effective_rank=search_depth + 1`.
- Provider failure must never become not-found.
- Ranking core must not import Stripe, frontend code, or MCP.
- SQLite is supported for development/tests; repository abstractions must remain compatible with PostgreSQL.
- No Redis/Celery in this plan.

## Review Focus

- Duplicate ASINs in one request should not create duplicate observations or duplicate provider probes.
- Zero/negative geo weights must fail validation rather than silently corrupt the weighted score.
- A provider timeout must fail the geo probe and must not create `SUCCESS_NOT_FOUND` observations.
- A successful SERP containing fewer results than the requested search depth must still use `search_depth + 1` for a missing ASIN.
- Empty geo-profile input must be rejected before provider work begins.

---

## File Map

```text
backend/
├── pyproject.toml
├── src/amazon_geo_rank_monitor/
│   ├── __init__.py
│   ├── config.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── errors.py
│   │   └── models.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── oxylabs.py
│   ├── ranking/
│   │   ├── __init__.py
│   │   ├── matcher.py
│   │   └── weighted.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── rank_repository.py
│   └── monitor/
│       ├── __init__.py
│       └── service.py
└── tests/
    ├── test_domain_models.py
    ├── test_matcher.py
    ├── test_weighted.py
    ├── test_oxylabs_provider.py
    ├── test_rank_repository.py
    └── test_monitor_service.py

config/
└── geo_profiles.example.yaml

.env.example
.gitignore
README.md
```

### Task 1: Python package scaffold and validated domain models

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/amazon_geo_rank_monitor/__init__.py`
- Create: `backend/src/amazon_geo_rank_monitor/domain/__init__.py`
- Create: `backend/src/amazon_geo_rank_monitor/domain/errors.py`
- Create: `backend/src/amazon_geo_rank_monitor/domain/models.py`
- Create: `backend/tests/test_domain_models.py`
- Create: `.gitignore`
- Create: `.env.example`

**Interfaces:**
- Produces: `GeoProfile`, `RankCheckRequest`, `SerpProduct`, `SerpResult`, `RankObservation`, `RankSnapshot`, `ProbeStatus`, `VerificationLevel`.
- Later tasks rely on these exact public names.

- [ ] **Step 1: Write the failing domain tests**

```python
from decimal import Decimal

import pytest
from pydantic import ValidationError

from amazon_geo_rank_monitor.domain.models import GeoProfile, RankCheckRequest


def test_geo_profile_requires_positive_weight() -> None:
    with pytest.raises(ValidationError):
        GeoProfile(
            id="us-ny-10001",
            name="New York",
            marketplace="amazon.com",
            ip_country="US",
            ip_postal_code="10001",
            delivery_country="US",
            delivery_postal_code="10001",
            device="desktop",
            weight=Decimal("0"),
        )


def test_rank_request_deduplicates_asins_preserving_order() -> None:
    request = RankCheckRequest(
        marketplace="amazon.com",
        keyword="walking pad",
        asins=["B0AAA11111", "B0AAA11111", "B0BBB22222"],
        geo_profiles=[
            GeoProfile(
                id="us-ny-10001",
                name="New York",
                marketplace="amazon.com",
                ip_country="US",
                ip_postal_code="10001",
                delivery_country="US",
                delivery_postal_code="10001",
                device="desktop",
                weight=Decimal("30"),
            )
        ],
        search_depth=100,
    )
    assert request.asins == ["B0AAA11111", "B0BBB22222"]
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend && python -m pytest tests/test_domain_models.py -q`  
Expected: FAIL because the package/models do not exist.

- [ ] **Step 3: Implement minimal Pydantic models**

Required behavior:
- ASINs normalized with `strip().upper()`.
- Duplicate ASINs removed in first-seen order.
- Empty keyword, empty ASIN list, empty geo profile list rejected.
- `search_depth >= 1`.
- Geo weight must be `> 0`.
- Device limited initially to `desktop | mobile`.
- `RankObservation` exposes `effective_rank` explicitly.

- [ ] **Step 4: Run tests and full suite**

Run: `cd backend && python -m pytest -q`  
Expected: all current tests PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add rank domain models`

### Task 2: Organic ASIN matcher and weighted-rank calculator

**Files:**
- Create: `backend/src/amazon_geo_rank_monitor/ranking/__init__.py`
- Create: `backend/src/amazon_geo_rank_monitor/ranking/matcher.py`
- Create: `backend/src/amazon_geo_rank_monitor/ranking/weighted.py`
- Create: `backend/tests/test_matcher.py`
- Create: `backend/tests/test_weighted.py`

**Interfaces:**
- Consumes: `SerpResult`, `RankObservation`, `GeoProfile`.
- Produces: `match_asins(result, asins, search_depth, geo_profile_id, provider, verification_level)` and `calculate_weighted_rank(observations, geo_profiles)`.

- [ ] **Step 1: Write failing matcher tests**

Tests must prove:
- organic positions are counted from `organic_products` only;
- sponsored appearance does not alter organic rank;
- missing ASIN receives `organic_rank=None`, `found=False`, `effective_rank=search_depth + 1`;
- duplicate request ASIN cannot produce duplicate observations.

- [ ] **Step 2: Run matcher tests and verify RED**

Run: `cd backend && python -m pytest tests/test_matcher.py -q`  
Expected: FAIL because matcher is missing.

- [ ] **Step 3: Implement matcher**

Core contract:

```python
def match_asins(
    result: SerpResult,
    asins: list[str],
    *,
    search_depth: int,
    geo_profile_id: str,
    provider: str,
    verification_level: VerificationLevel,
) -> list[RankObservation]:
    ...
```

Ranks are 1-based.

- [ ] **Step 4: Write failing weighted-rank tests**

```python
def test_calculates_normalized_weighted_rank() -> None:
    # ranks 3, 5, 4 with weights 30, 40, 30 => 4.1
    ...


def test_missing_observation_uses_effective_rank() -> None:
    # a missing geo with effective rank 101 contributes according to its weight
    ...
```

Also test mismatched/unknown geo IDs fail clearly.

- [ ] **Step 5: Run weighted tests and verify RED**

Run: `cd backend && python -m pytest tests/test_weighted.py -q`  
Expected: FAIL because calculator is missing.

- [ ] **Step 6: Implement weighted calculator**

Use `Decimal` internally, return quantized decimal without binary-float accumulation.

- [ ] **Step 7: Run the full suite**

Run: `cd backend && python -m pytest -q`  
Expected: PASS.

- [ ] **Step 8: Commit**

Commit message: `feat: add rank matching and weighting`

### Task 3: Provider protocol and Oxylabs managed-search adapter

**Files:**
- Create: `backend/src/amazon_geo_rank_monitor/providers/__init__.py`
- Create: `backend/src/amazon_geo_rank_monitor/providers/base.py`
- Create: `backend/src/amazon_geo_rank_monitor/providers/oxylabs.py`
- Create: `backend/tests/test_oxylabs_provider.py`

**Interfaces:**
- Consumes: `GeoProfile`, `SerpProduct`, `SerpResult`.
- Produces: `RankProvider` protocol and `OxylabsRankProvider.search(...)`.

- [ ] **Step 1: Write failing provider contract tests**

Inject a fake Oxylabs client object; do not call the network.

Fixture response must contain parsed `results.organic` and sponsored entries.

Assert:
- query, domain, geo location, device, parse flag, and page count are sent;
- parsed products normalize ASIN to uppercase;
- provider metadata is stored separately from ranking logic;
- malformed response raises `ProviderResponseError`;
- timeout/provider exception raises `ProviderUnavailableError`, not an empty SERP.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_oxylabs_provider.py -q`  
Expected: FAIL because provider adapter is missing.

- [ ] **Step 3: Implement protocol and adapter**

`RankProvider` signature:

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
    ) -> SerpResult: ...
```

For Amazon US, map `amazon.com` to Oxylabs domain `com`.

Use the official SDK interface behind an injected client factory so unit tests remain offline.

- [ ] **Step 4: Run full suite**

Run: `cd backend && python -m pytest -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add Oxylabs rank provider`

### Task 4: SQLAlchemy rank persistence with SQLite

**Files:**
- Create: `backend/src/amazon_geo_rank_monitor/repositories/__init__.py`
- Create: `backend/src/amazon_geo_rank_monitor/repositories/models.py`
- Create: `backend/src/amazon_geo_rank_monitor/repositories/rank_repository.py`
- Create: `backend/tests/test_rank_repository.py`

**Interfaces:**
- Consumes: domain observations/snapshots.
- Produces: `RankRepository.create_run`, `save_observations`, `save_snapshots`, `complete_run`, `get_run`.

- [ ] **Step 1: Write failing repository tests**

Use `sqlite+pysqlite:///:memory:` and prove:
- a run can be created;
- observations and snapshots are persisted;
- `organic_rank=None` remains NULL while `effective_rank` is persisted;
- a completed run can be read back with its observations;
- duplicate observation identity within the same run is rejected by a uniqueness constraint.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && python -m pytest tests/test_rank_repository.py -q`  
Expected: FAIL because repository is missing.

- [ ] **Step 3: Implement SQLAlchemy models/repository**

Use SQLAlchemy 2 declarative models and a passed-in `Engine`/session factory.

Do not hard-code SQLite-specific SQL.

- [ ] **Step 4: Run full suite**

Run: `cd backend && python -m pytest -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: persist rank runs and observations`

### Task 5: Rank monitor orchestration with shared SERP probes

**Files:**
- Create: `backend/src/amazon_geo_rank_monitor/monitor/__init__.py`
- Create: `backend/src/amazon_geo_rank_monitor/monitor/service.py`
- Create: `backend/tests/test_monitor_service.py`

**Interfaces:**
- Consumes: `RankProvider`, matcher, weighted calculator, `RankRepository`.
- Produces: `RankMonitorService.check(request) -> list[RankSnapshot]`.

- [ ] **Step 1: Write failing orchestration tests**

Create an in-memory fake provider that records calls.

Prove:
- 2 ASINs × 3 geo profiles triggers exactly 3 provider calls, not 6;
- every successful geo result is matched against both ASINs;
- weighted snapshot is calculated independently for each ASIN;
- an empty geo list is rejected before provider calls;
- provider timeout causes run failure/partial status and does not fabricate not-found observations;
- duplicate ASINs do not duplicate observations.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && python -m pytest tests/test_monitor_service.py -q`  
Expected: FAIL because service is missing.

- [ ] **Step 3: Implement `RankMonitorService`**

Execution:
1. validate request;
2. create run;
3. call provider once per geo profile;
4. match all request ASINs against each result;
5. persist successful observations;
6. calculate per-ASIN weighted snapshots only when sufficient valid observations exist;
7. mark run `succeeded`, `partially_succeeded`, or `failed`.

Provider failure must be recorded as run error metadata, not a missing-ASIN observation.

- [ ] **Step 4: Run full suite**

Run: `cd backend && python -m pytest -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: orchestrate geographic rank checks`

### Task 6: Configuration examples and runnable rank-core documentation

**Files:**
- Create: `backend/src/amazon_geo_rank_monitor/config.py`
- Create: `config/geo_profiles.example.yaml`
- Create/Modify: `README.md`
- Modify: `.env.example`
- Add tests to: `backend/tests/test_domain_models.py` or create `backend/tests/test_config.py`

**Interfaces:**
- Produces: environment settings and YAML geo-profile loader usable by later REST/MCP plans.

- [ ] **Step 1: Write failing config tests**

Test:
- valid YAML loads independent IP and delivery postal codes;
- malformed/zero weight fails validation;
- weights do not need to sum to 100;
- missing Oxylabs credentials are allowed while importing/configuring the app, but provider construction fails with a clear configuration error.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && python -m pytest tests/test_config.py -q`  
Expected: FAIL because config loader is missing.

- [ ] **Step 3: Implement configuration loader and examples**

Example YAML includes New York, Los Angeles, Dallas, Miami, and Seattle profiles with illustrative weights.

README must document:
- scope and non-goals;
- environment setup;
- local test command;
- rank semantics;
- one-SERP/multi-ASIN behavior;
- weighted formula;
- managed vs future strict verification boundary.

- [ ] **Step 4: Run quality gates**

Run:
- `cd backend && python -m pytest -q`
- `cd backend && ruff check src tests`

Expected: PASS with no warnings/errors.

- [ ] **Step 5: Commit**

Commit message: `docs: document rank core configuration`

## Phase Completion Gate

Before this plan is complete:

1. `cd backend && python -m pytest -q` passes.
2. `cd backend && ruff check src tests` passes.
3. No production file imports Stripe, FastAPI, frontend, or MCP.
4. A service test demonstrates that two ASINs across three geo profiles produce three provider calls.
5. A repository test demonstrates not-found persists as `organic_rank=NULL` and `effective_rank=search_depth+1`.
6. Oxylabs tests run fully offline.
7. No secrets or real credentials are committed.

## Subsequent Separate Plans

After this plan is green, create and execute separate implementation plans for:

1. strict browser + residential-proxy verification;
2. FastAPI + DB worker + API keys + official MCP v2;
3. prepaid credits + Stripe;
4. Fantastic Admin Basic / Element Plus SaaS frontend.
