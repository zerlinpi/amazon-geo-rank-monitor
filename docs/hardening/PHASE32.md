# Phase 32 evidence and operating limits

## Baseline

- Initial read: `1ce080f`; refreshed main: `2ef06d5` on 2026-09-30. No open PRs at refresh.
- Branch: `chore/production-hardening`; pre-change backend: 247 passed / 6 service-dependent skips.
- Alembic: one head `20260928_0021`; no published revision modified.
- Prior intermittent CI failure: invalid SSO signature fixture replaced the first byte with `x`,
  which could already equal that byte. XOR corruption now always changes the signature.

## Cleanup

Removed nine unrelated VOC/review-scraping workflows (Reddit, Trustpilot, Hugging Face
and temporary WalkingPad exports). Product SERP fixtures containing a sample `walking pad`
keyword remain valid rank-monitor tests. No product provider, strict verification, cache,
billing, competitive intelligence, rank or tenant code is removed. Research branches
remain separate and are not merged into main.

## Verification matrix

| Area | Evidence |
| --- | --- |
| Core offline business | `test_business_e2e.py`: real registration/workspace, 3 geos, 2 ASINs, queued worker, snapshots, history/analytics and cache billing; 3 upstream SERPs across 2 runs |
| Strict geography and rank semantics | Existing strict_browser, strict_domain, playwright_amazon, matcher, weighted, monitor_service and auto_strict_policy tests retained |
| Budget invariants | Existing billed_rank_execution, billing_repository, auto_strict_policy, strict_budget_forecast and rank_jobs tests retained |
| PostgreSQL | Dedicated CI: 4 existing integration + 6 hardening cases (fresh migration/schema/rollback, job/report deduplication, cooldown, ignored/paid webhooks, cache upsert/hits) |
| Redis | Dedicated CI: shared limiter plus no plaintext identity key |
| Frontend | 6 date helper tests including DST ambiguity; explicit vue-tsc; production Vite build |
| Browser | 5 scenarios × UTC/New York/Singapore: login/dashboard, history pagination/lazy detail, combined/empty filters, UTC ranges/shortcuts/clear, failure/loading/retry and worker result |
| Containers | CI builds backend/frontend and checks DB/Redis/migrate/API/worker/scheduler/frontend readiness, SCIM ingress, both forwarding trust boundaries and query-free callback logs |
| APIs | Existing tenant/RBAC/CSRF/MFA/OIDC/SCIM/history tests; tenant-scoped operations and retries; generic 500 safe JSON with request ID; frontend Axios contract uses explicit response.data |
| Long tasks | Real database regressions verify fresh worker health before lease renewal and fresh scheduler health during synchronous report delivery; refreshes preserve status and processed counts |
| Performance | Cursor summary remains indexed and lightweight; no eager detail downloads; local UI actions do not trigger hidden paid probes |

## Security audit

Review exposed and fixed an existing cross-workspace operations boundary: job lists,
requeues and queue/verification metrics now enforce the current tenant; shared worker
status omits private job IDs/errors. A regression proves a second tenant cannot read
or requeue a victim job. SMTP delivery failures persist only the exception class.
Explicit ingress trust prevents client IP spoofing and avoids a shared authentication
limit for all frontend users. Default query-bearing access logs are disabled while
application path-only request logs remain enabled.

Python locked runtime audit: no known vulnerabilities after cryptography 50.0.1.
Frontend full upstream workspace after the checked-in patch: 0 critical/high/moderate,
1 low (`GHSA-5j4c-8p2g-v4jx`, Vue 2.7.16 through unused `apps/example` →
`@types/splitpanes`). The shipped `core-element-plus` application uses Vue 3.5.42.
The example is not included in the production bundle. Follow-up: remove/upgrade the
unused upstream example dependency on the next upstream refresh; review by 2026-10-30.
Do not globally suppress Vue advisories or force Vue 2 consumers onto Vue 3.
The original high/critical findings in minimist and fast-uri are resolved; qs/esbuild
are updated through a reproducible patch, with a frozen lockfile check in CI.
The subsequent fresh CI audit detected additional advisories: brace-expansion is
now pinned to 5.0.12 (GHSA-qhr7-859c-m2p7, GHSA-6j4f-fj2g-mc7p,
GHSA-q2hr-2g5m-vwhr) and fast-uri to 3.1.8 (GHSA-hrr3-gc8f-f4qj).
These are targeted patch updates within the major versions already in the lockfile.

A fresh 2026-10-08 registry audit added `shell-quote`
(`GHSA-pqg4-j6r4-53mv`) and `source-map-js` (`GHSA-68fv-2mgg-jv7q`);
the pinned upstream patch now resolves them to 1.12.0 and 1.2.2 respectively.
The same audit added `braces` `GHSA-vfj7-8cjw-p6xm`. npm still has no
patched `braces` release, so CI does not use a blanket suppression. It first
runs a zero-exception high/critical audit over all production dependencies,
then runs the complete workspace audit with only that exact GHSA ignored for
development tooling. If `braces` ever enters a production dependency graph,
the first audit becomes a release blocker. Recheck the exception on every
upstream refresh and remove it immediately when a patched release is available.

Gitleaks is redacted and checks all fetched history plus the tracked working tree.
A passing result is a point-in-time scan, not proof that credentials never existed.
No real secret findings were reported in the initial full-history scan. The final
scan and exact-commit CI links are recorded in the PR.

## Environmental and operational limits

- Local Docker/PostgreSQL/Redis services are unavailable; these checks must pass in
  GitHub Actions before merge. Skips in the local suite are not integration passes.
- Local downloaded Chrome crashes at startup; browser test definitions alone are
  not evidence of success. The independent E2E job must prove all 15 cases.
- Ruleset writes are unavailable through the connector; see `docs/GITHUB_RULESET.md`.
  Protection setup remains an administrator action until independently verified.
- Git push authentication is unavailable for ref deletion; an authorized deletion
  of only proven ancestors failed before changing any remote refs. No branches deleted.
- SMTP, paid provider geography, production proxy/TLS and Stripe production delivery
  are outside offline validation and need controlled staging checks before release.
- No release tag or Phase 33 scope is authorized by this readiness work.

Local post-review verification: **265 passed, 12 service-dependent skips**, Ruff,
compileall and Compose configuration checks passed. The skips are ten PostgreSQL
and two Redis cases; dedicated CI must run them. The first real CI run
[36657460980](https://github.com/zerlinpi/amazon-geo-rank-monitor/actions/runs/36657460980)
passed backend, frontend, Redis, security and full container startup. It exposed
missing tenant rows in PostgreSQL test setup (7 passed / 3 failed) and an inaccessible
browser test selector (12 passed / 3 failed); both fixtures were corrected. Final
post-review integration results and the exact checked commit are maintained in
[PR #48](https://github.com/zerlinpi/amazon-geo-rank-monitor/pull/48). Earlier green
jobs do not substitute for a complete green run on the final head.

## Remote branch ancestry

Classification against `2ef06d5`. Squash-merged branches are preserved unless their
actual tip is an ancestor; a merged PR alone is not deletion proof. Research/data
branches with unmerged content remain untouched.

| Branch | Tip | Disposition |
| --- | --- | --- |
| `data/walking-pad-reviews-200k` | `a532dd30f1` | Preserve: tip is not an ancestor |
| `feat/account-recovery-email-security` | `8f9d4a7f3e` | Ancestor; deletion BLOCKED by push credentials |
| `feat/alert-incident-reliability` | `8e96d62cfe` | Ancestor; deletion BLOCKED by push credentials |
| `feat/api-security-hardening` | `4c5bf08c6f` | Ancestor; deletion BLOCKED by push credentials |
| `feat/api-worker-mcp` | `5eac32404c` | Ancestor; deletion BLOCKED by push credentials |
| `feat/audit-redis-observability` | `909869a45e` | Ancestor; deletion BLOCKED by push credentials |
| `feat/auth-observability-postgres` | `b9e08efe43` | Ancestor; deletion BLOCKED by push credentials |
| `feat/auto-strict-confidence-ui` | `e4262b66ff` | Preserve: tip is not an ancestor |
| `feat/auto-strict-observability` | `c7384c0827` | Preserve: tip is not an ancestor |
| `feat/auto-strict-probe-budget` | `c4492bc093` | Preserve: tip is not an ancestor |
| `feat/auto-strict-verification` | `622e62ba04` | Preserve: tip is not an ancestor |
| `feat/browser-session-security` | `3d61774313` | Ancestor; deletion BLOCKED by push credentials |
| `feat/competitive-trend-alerts` | `d2b6e0d3d8` | Preserve: tip is not an ancestor |
| `feat/credits-stripe` | `e7089d4022` | Preserve: tip is not an ancestor |
| `feat/daily-strict-budget-status` | `3764b10386` | Preserve: tip is not an ancestor |
| `feat/daily-strict-credit-budget` | `7294461312` | Preserve: tip is not an ancestor |
| `feat/enterprise-oidc-sso` | `ea2252134b` | Ancestor; deletion BLOCKED by push credentials |
| `feat/fantastic-admin-saas-ui` | `c49e100031` | Ancestor; deletion BLOCKED by push credentials |
| `feat/fantastic-admin-ui` | `c066baa7f7` | Preserve: tip is not an ancestor |
| `feat/historical-analytics-reports` | `0a6d1fa588` | Preserve: tip is not an ancestor |
| `feat/job-reliability-operations` | `58b3ee8145` | Ancestor; deletion BLOCKED by push credentials |
| `feat/manual-strict-verification` | `eb2c6a43b3` | Preserve: tip is not an ancestor |
| `feat/monitor-auto-strict-policy` | `458d2d875f` | Preserve: tip is not an ancestor |
| `feat/prepaid-credits-stripe` | `6e46203f27` | Ancestor; deletion BLOCKED by push credentials |
| `feat/production-scheduler-migrations` | `1333e1fa98` | Ancestor; deletion BLOCKED by push credentials |
| `feat/rank-alerts-notifications` | `5b12fe5a25` | Preserve: tip is not an ancestor |
| `feat/rank-core-foundation` | `b1ad37db9f` | Ancestor; deletion BLOCKED by push credentials |
| `feat/run-history-date-filter` | `5f498c9085` | Preserve: tip is not an ancestor |
| `feat/run-history-pagination` | `3d2106fdb4` | Preserve: tip is not an ancestor |
| `feat/run-history-strict-budget-evidence` | `4f60974516` | Preserve: tip is not an ancestor |
| `feat/saas-accounts-rbac` | `a6f0d7fd2d` | Ancestor; deletion BLOCKED by push credentials |
| `feat/scim-provisioning` | `e4127e3b83` | Preserve: tip is not an ancestor |
| `feat/serp-competitive-intelligence` | `e3f15605f5` | Preserve: tip is not an ancestor |
| `feat/serp-probe-cache` | `8dff1b896d` | Preserve: tip is not an ancestor |
| `feat/strict-budget-exhaustion-forecast` | `e9a6d752e7` | Preserve: tip is not an ancestor |
| `feat/strict-budget-forecast-alert` | `4f8b847019` | Preserve: tip is not an ancestor |
| `feat/strict-budget-forecast-runway-alert` | `22b68cebc0` | Preserve: tip is not an ancestor |
| `feat/strict-budget-pacing` | `642d6b58a1` | Preserve: tip is not an ancestor |
| `feat/strict-budget-pacing-deferred-alert` | `bd0a96c166` | Preserve: tip is not an ancestor |
| `feat/strict-budget-threshold-alerts` | `b76a6b4b4c` | Preserve: tip is not an ancestor |
| `feat/strict-budget-utilization-alerts` | `750d55b10e` | Preserve: tip is not an ancestor |
| `feat/strict-pacing-analytics` | `b9f1173f75` | Ancestor; deletion BLOCKED by push credentials |
| `feat/strict-rank-verification` | `0f4343a669` | Ancestor; deletion BLOCKED by push credentials |
| `feat/strict-verification-alerts` | `4bb49c7300` | Preserve: tip is not an ancestor |
| `feat/totp-mfa-workspace-policy` | `95c7b20683` | Ancestor; deletion BLOCKED by push credentials |
| `feat/verification-analytics` | `d8bd3e6411` | Preserve: tip is not an ancestor |
| `feat/workspace-auto-strict-policy` | `836128bacb` | Preserve: tip is not an ancestor |
| `fix/alert-cooldown-atomicity` | `3d41c4ecc7` | Preserve: tip is not an ancestor |
| `fix/alert-cooldown-atomicity-main` | `224064b4f2` | Preserve: tip is not an ancestor |
| `tmp/walking-pad-voc-10k` | `e0deb4d596` | Preserve: tip is not an ancestor |
| `tmp/walking-pad-voc-200k-2024-2026` | `71b755b147` | Preserve: tip is not an ancestor |
