# Strict Geographic Rank Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strict Amazon rank-verification path that independently verifies residential proxy geography and Amazon Deliver-to geography before accepting browser-derived SERP results.

**Architecture:** A strict provider composes three pieces: a residential proxy credential builder, a browser client protocol, and a Playwright implementation. The browser context uses one requested residential proxy, verifies its observed IP geography, sets and confirms the Amazon delivery ZIP, then searches Amazon and returns provider-neutral `SerpResult` data. Any CAPTCHA/block, proxy-geo mismatch, or unconfirmed delivery address fails closed and produces no rank observation.

**Tech Stack:** Python 3.12+, existing Pydantic domain, Playwright Python async API, pytest/pytest-asyncio, existing provider protocol.

**Spec:** `docs/superpowers/specs/2026-09-24-amazon-geo-rank-saas-design.md`

## Global Constraints

- No CAPTCHA solving, stealth plugins, fingerprint spoofing, or anti-bot bypass techniques.
- CAPTCHA/block detection returns `UPSTREAM_BLOCKED`.
- Requested IP geography and Amazon delivery geography must be independently verified.
- Strict verification runs in an isolated clean BrowserContext.
- Strict failures never overwrite a valid managed observation.
- Browser/provider credentials never appear in returned SERP content, logs, or frontend-facing metadata.
- Existing Phase 1 provider-neutral matcher and weighted-rank logic remain unchanged unless a regression test requires a fix.
- Official Playwright APIs are used for context proxy configuration and isolated sessions.
- No billing, REST, MCP, or frontend code in this plan.

## Review Focus

- A proxy that connects but resolves to the wrong requested postal code must fail strict verification.
- A delivery ZIP setter that submits successfully but cannot confirm the requested ZIP must fail closed.
- A CAPTCHA/robot-check page must be classified as blocked, not parsed as an empty SERP.
- Sponsored cards must not be included in the strict provider's organic collection.
- Search pagination must stop at the configured search depth and never loop indefinitely.

---

### Task 1: Strict verification domain records and error mapping

**Files:**
- Modify: `backend/src/amazon_geo_rank_monitor/domain/models.py`
- Modify: `backend/src/amazon_geo_rank_monitor/domain/errors.py`
- Create: `backend/tests/test_strict_domain.py`

**Interfaces:**
- Produces: `ProxyLocation`, `GeoVerificationResult`, `StrictProbeMetadata`, `UpstreamBlockedError`, `GeoVerificationError`.

- [ ] **Step 1: Write failing tests**

```python
from amazon_geo_rank_monitor.domain.models import ProxyLocation, GeoVerificationResult

def test_geo_verification_requires_both_ip_and_delivery_confirmation() -> None:
    result = GeoVerificationResult(
        requested_ip_postal_code="10001",
        observed_ip=ProxyLocation(country="US", postal_code="10001"),
        requested_delivery_postal_code="10001",
        confirmed_delivery_postal_code="10001",
    )
    assert result.ip_verified is True
    assert result.delivery_verified is True
    assert result.strict_verified is True
```

Add mismatch cases for country/postal code and delivery ZIP.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && python -m pytest tests/test_strict_domain.py -q`  
Expected: FAIL because strict verification records do not exist.

- [ ] **Step 3: Implement minimal models/errors**

`ProxyLocation` fields: `ip`, `country`, `state`, `city`, `postal_code`.

`GeoVerificationResult` stores requested/observed IP and requested/confirmed delivery values and exposes computed booleans `ip_verified`, `delivery_verified`, `strict_verified`.

- [ ] **Step 4: Run full suite**

Run: `cd backend && python -m pytest -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

Commit: `feat: add strict geo verification domain`

### Task 2: Residential proxy configuration without secret leakage

**Files:**
- Create: `backend/src/amazon_geo_rank_monitor/providers/residential_proxy.py`
- Create: `backend/tests/test_residential_proxy.py`
- Modify: `backend/src/amazon_geo_rank_monitor/config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `BrowserProxyConfig`, `OxylabsResidentialProxyFactory.build(geo_profile, session_id)`.

- [ ] **Step 1: Write failing tests**

Prove:
- requested country and postal code are encoded in the proxy username;
- a stable session id is encoded for a single strict probe;
- passwords are never present in `repr()` / string form;
- missing proxy credentials fail at factory construction, not at package import.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && python -m pytest tests/test_residential_proxy.py -q`.

- [ ] **Step 3: Implement factory**

Default endpoint:
`http://pr.oxylabs.io:7777`

Username pattern:
`customer-{username}-cc-{COUNTRY}-postalcode-{POSTAL}-sessid-{SESSION}`

If no requested postal code is present, country targeting remains supported, but strict `ip_verified` can only verify fields that were requested.

`BrowserProxyConfig` contains `server`, `username`, `password`, but redacts the password from representations.

- [ ] **Step 4: Run full suite and commit**

Run: `cd backend && python -m pytest -q`  
Commit: `feat: add residential proxy configuration`

### Task 3: Browser client protocol and strict-provider orchestration

**Files:**
- Create: `backend/src/amazon_geo_rank_monitor/providers/browser_client.py`
- Create: `backend/src/amazon_geo_rank_monitor/providers/strict_browser.py`
- Modify: `backend/src/amazon_geo_rank_monitor/providers/__init__.py`
- Create: `backend/tests/test_strict_browser_provider.py`

**Interfaces:**
- `AmazonBrowserClient.verify_ip_location() -> ProxyLocation`
- `AmazonBrowserClient.set_delivery_location(postal_code) -> str | None`
- `AmazonBrowserClient.search(keyword, marketplace, search_depth) -> SerpResult`
- `StrictBrowserRankProvider.search(...) -> SerpResult`

- [ ] **Step 1: Write failing provider tests using a fake browser client**

Prove:
- proxy factory called once per probe;
- browser client receives the generated proxy;
- observed IP mismatch raises `GeoVerificationError`;
- delivery ZIP mismatch raises `GeoVerificationError`;
- a successful strict probe adds `verification_level=strict`, requested and observed IP metadata, and confirmed delivery ZIP;
- blocked browser error propagates as `UpstreamBlockedError`.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && python -m pytest tests/test_strict_browser_provider.py -q`.

- [ ] **Step 3: Implement strict provider**

Execution order:
1. create unique session id;
2. build proxy config;
3. open one isolated browser client/context with that proxy;
4. verify observed proxy location;
5. validate requested IP fields against observed fields;
6. open Amazon and set Deliver-to ZIP;
7. confirm Deliver-to ZIP;
8. execute search;
9. attach verification metadata;
10. close context in `finally`.

- [ ] **Step 4: Run full suite and commit**

Run: `cd backend && python -m pytest -q`  
Commit: `feat: add strict browser rank provider`

### Task 4: Playwright Amazon browser implementation

**Files:**
- Create: `backend/src/amazon_geo_rank_monitor/providers/playwright_amazon.py`
- Create: `backend/tests/test_playwright_amazon.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces concrete `PlaywrightAmazonBrowserClient` satisfying the Task 3 protocol.

- [ ] **Step 1: Write failing adapter tests with fake Playwright page/context objects**

Tests pin these behaviors rather than real Amazon network access:
- context is created with supplied HTTP proxy server/username/password;
- context is isolated per probe;
- location endpoint JSON maps into `ProxyLocation`;
- block/CAPTCHA markers cause `UpstreamBlockedError`;
- search-result cards with `data-asin` are collected in DOM order;
- sponsored cards enter sponsored results and are excluded from organic results;
- each returned `SerpProduct.position` is the mixed product-card position;
- pagination stops once `search_depth` product cards are collected or no next page exists.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && python -m pytest tests/test_playwright_amazon.py -q`.

- [ ] **Step 3: Implement normal browser flow**

Use async Playwright.

Normal interaction only:
- isolated context with proxy;
- `https://ip.oxylabs.io/location` to observe proxy geography;
- Amazon home/location control to set delivery ZIP;
- Amazon search URL for keyword;
- public search-result card DOM extraction;
- normal next-page navigation.

Block detection checks for Amazon robot/captcha markers and returns an error. Do not add CAPTCHA-solving, stealth, fingerprint spoofing, or challenge avoidance.

- [ ] **Step 4: Update dependency**

Add:
`playwright>=1.55,<2`

CI does not need to install Chromium for fake-object unit tests. Runtime deployment docs will require `playwright install chromium`.

- [ ] **Step 5: Run full suite + Ruff and commit**

Run:
- `cd backend && python -m pytest -q`
- `cd backend && ruff check src tests`

Commit: `feat: implement Playwright strict verification client`

### Task 5: Strict verification documentation and configuration

**Files:**
- Modify: `README.md`
- Modify: `config/geo_profiles.example.yaml`
- Modify: `.env.example`
- Add/modify tests as required.

**Interfaces:**
- Documents the strict verification runtime without exposing secrets.

- [ ] **Step 1: Add configuration tests**

Prove configuration can load strict proxy settings without requiring them for managed-only use.

- [ ] **Step 2: Document runtime**

Document:
- managed versus strict semantic difference;
- proxy verification + delivery verification sequence;
- required residential proxy environment variables;
- `playwright install chromium`;
- block/CAPTCHA behavior;
- strict checks are expensive and intended for anomalies/manual verification.

- [ ] **Step 3: Quality gates**

Run:
- `cd backend && python -m pytest -q`
- `cd backend && ruff check src tests`

Expected: PASS.

- [ ] **Step 4: Commit**

Commit: `docs: document strict geographic verification`

## Phase Completion Gate

- Existing Phase 1 tests remain green.
- Strict provider fails closed on IP mismatch and delivery mismatch.
- CAPTCHA/block pages are explicit errors.
- No anti-bot bypass or CAPTCHA-solving code exists.
- Playwright implementation uses an isolated context and configured proxy.
- Strict result metadata proves both requested/observed IP geography and requested/confirmed delivery ZIP.
- No credentials appear in result metadata or repr output.
- GitHub CI passes before the phase is proposed for merge.
