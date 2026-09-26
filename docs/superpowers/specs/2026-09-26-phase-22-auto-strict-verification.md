# Phase 22 — Automatic Strict Verification

## Goal

Automatically escalate suspicious managed SERP results to strict browser verification while preserving tenant isolation, existing billing semantics, cache provenance, and completed-run reliability.

## Triggers

Phase 22 introduces a policy layer that may request strict verification for a geo probe when one or more of these conditions are met:

1. Large rank movement versus the previous successful monitor run.
2. Managed result is not-found after the ASIN was recently found.
3. Aggregate confidence falls below a configurable threshold.
4. Managed provider geo metadata is inconsistent with the requested geo profile.
5. A manually forced strict-verification flag is present.

Default thresholds must be conservative and configurable. Automatic escalation is disabled unless strict provider credentials are configured.

## Execution model

Managed probe remains the primary measurement.

When escalation is triggered:

- run one strict browser probe for the same marketplace, keyword, geo profile, device, and search depth;
- persist both managed and strict observations;
- mark the strict observation as the preferred verification result for that geo;
- never overwrite or delete the original managed observation;
- record why escalation occurred;
- expose escalation metadata in run history and API responses.

Strict verification failure must not invalidate a successful managed probe. The run remains usable and records the strict failure separately.

## Manual force semantics

A caller may force strict verification for a single managed execution without
changing the saved Workspace or Monitor policy.

Supported entry points:

- REST `POST /api/v1/rank/check` with
  `force_strict_verification=true`;
- REST `POST /api/v1/monitors/{id}/run` with the same flag;
- MCP `check_rank` and `run_monitor`;
- Fantastic Admin Rank Explorer **Force strict** and Monitor **Verify now**.

Manual force keeps the managed probe as the primary measurement and requests a
strict probe for each managed Geo. Both observations remain persisted and a
successful strict observation becomes the preferred result for that Geo.

Policy precedence is:

```text
runtime global kill switch
  -> workspace default
  -> monitor override
  -> one-run manual force
```

Manual force may override a Workspace or Monitor `Off` setting, but it must
never bypass the runtime global kill switch. It also remains subject to strict
cache compatibility, prepaid credits, and the per-run strict upstream probe
budget.

For queued Monitor runs the force flag is snapshotted into the job payload so
retries preserve the exact execution intent. Run evidence records the
`manual_force` trigger and whether the runtime kill switch allowed the
verification path.

## Billing

Billing remains probe-based.

- Managed upstream probe: existing managed rate.
- Strict upstream probe: existing strict/browser-verified rate.
- Cache hits are not billed as new upstream probes.
- Automatic strict escalation reserves and settles credits only when an upstream strict probe is actually attempted.
- If insufficient credits are available for escalation, keep the managed result and record `strict_verification_skipped=insufficient_credits`.

No per-ASIN surcharge is introduced.

## Cache policy

Managed and strict results must use separate cache namespaces.

Automatic strict verification must not reuse a managed cache entry as a strict result.

Strict cache reuse is allowed only when:

- provider mode is strict;
- geo profile, marketplace, keyword, device, and depth are compatible;
- the strict TTL policy is satisfied.

The run must expose whether strict verification came from upstream or cache.

## Data model additions

Add run/probe metadata sufficient to answer:

- was strict escalation requested?
- why?
- was it executed, cached, skipped, or failed?
- which provider produced the preferred result?
- how many managed and strict upstream probes were billed?

Prefer additive columns or a dedicated verification-attempt table over mutating historical observation semantics.

## API

Extend serialized execution/run-history output with:

- `verification.auto_strict_enabled`
- `verification.strict_attempted`
- `verification.strict_succeeded`
- `verification.strict_skipped_reason`
- `verification.triggers[]`
- usage split for managed/strict upstream probes and cache hits

Add configuration surface only after backend policy is stable.

## Worker behavior

The database worker must use the same escalation policy as synchronous rank checks.

Retries must not double-charge strict probes.

A retry may reuse a compatible strict cache entry created by the previous attempt.

## Observability

Add counters:

- automatic strict escalation requested
- strict escalation executed
- strict escalation cache hit
- strict escalation skipped by credits/configuration
- strict escalation failed
- strict escalation succeeded

Logs must include tenant ID, run ID, geo profile ID, trigger reason, and provider mode without leaking credentials.

## Tests

Required regression coverage:

1. no escalation under normal stable managed result;
2. large rank movement triggers strict verification;
3. managed not-found after recent found triggers strict verification;
4. strict success becomes preferred without deleting managed observation;
5. strict failure preserves managed success;
6. insufficient credits skips strict probe without failing the run;
7. retry is idempotent for billing;
8. managed cache never satisfies strict verification;
9. strict cache hit does not create a new strict billable probe;
10. tenant isolation across history lookup and escalation policy;
11. worker and synchronous API produce equivalent policy outcomes.

## Rollout

1. Policy module + unit tests.
2. Persistence and usage accounting.
3. Synchronous execution path.
4. Worker execution path.
5. API serialization and metrics.
6. Fantastic Admin visibility.
7. Documentation and migration verification.

Phase 22 should ship behind an environment/configuration flag until production strict-provider credentials and credit policy are confirmed.
