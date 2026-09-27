# Phase 24 — Workspace Daily Strict Credit Guardrail

## Goal

Put a hard Workspace-level ceiling on **new paid Strict Verification credits per
UTC day**.

The existing per-run strict probe budget limits one execution. It does not stop
many scheduled Monitors, manual checks, or multiple workers from cumulatively
spending more Strict Verification credits than a Workspace intends.

Phase 24 adds a live daily guardrail that is enforced at the billing reservation
boundary.

## Configuration

Workspace verification policy adds:

```text
daily_credit_budget: integer | null
```

Semantics:

- `null` — unlimited daily Strict Verification credits;
- `0` — block every new paid Auto Strict / manually forced strict probe;
- positive integer — maximum committed Strict Verification credits for the UTC
  day.

The supported range is 0 through 1,000,000 credits.

Fantastic Admin exposes this under **Workspace → Team → Automatic strict
verification → Workspace spend guardrail**.

## Live policy semantics

The daily credit cap is intentionally **not** snapshotted into queued jobs.

A queued Monitor job still snapshots its normal verification behavior:

- enabled / disabled inheritance;
- minimum confidence;
- maximum strict upstream probes per run;
- one-run manual force intent.

But immediately before execution the Worker reads the Workspace's current
`daily_credit_budget`.

This means an administrator can lower the daily cap to `0` and stop new paid
Strict Verification even for jobs that were already queued.

Immediate Rank Explorer / REST / MCP checks also read the current Workspace
policy before execution.

Manual force does not bypass the daily credit guardrail.

## Billing boundary

The guardrail is enforced by `BillingRepository.reserve` for reservations whose
reference type is:

```text
auto_strict_verification
```

Before creating a new reservation, the repository locks the Workspace credit
account row and calculates committed credits in the current UTC-day window:

```text
committed =
    sum(amount for status=reserved)
  + sum(settled_amount for status=settled)
```

Rows with `status=released` do not consume the daily budget.

The new reservation is rejected when:

```text
committed + requested_credits > daily_credit_budget
```

This uses the same database transaction and credit-account row lock already
used for balance reservations. On PostgreSQL, concurrent workers therefore
serialize at the Workspace credit account and cannot independently overspend
the final remaining daily allowance.

An idempotent retry that finds its existing reservation returns that reservation
rather than consuming budget a second time.

## UTC day boundary

The current budget window begins at:

```text
00:00:00 UTC
```

and naturally resets as the next UTC day begins.

This phase intentionally uses UTC rather than a configurable Workspace timezone
so workers and API replicas share one unambiguous accounting boundary.

## Cache behavior

The strict probe cache is checked before billing reservation.

A compatible strict cache hit therefore remains allowed after the daily paid
credit cap is exhausted because it requires no new provider probe and no new
credits.

The guardrail limits **new paid Strict Verification**, not the use of already
paid compatible evidence.

## Run evidence

Every managed run records the daily cap that was effective when it executed:

```text
verification_metadata.auto_strict_daily_credit_budget
```

When the cap prevents a new paid strict probe, the verification event records:

```text
skipped_reason = daily_credit_budget_exhausted
```

Run History shows the effective daily budget with the other verification
evidence.

## Alerts and analytics

Rank Alerts adds:

```text
strict_daily_budget_exhausted
```

The rule is probe-level and can optionally scope to a Geo, consistent with the
other Strict Verification operational alerts.

System Status verification analytics includes
`daily_credit_budget_exhausted` in its skip-reason breakdown automatically.

Because Phase 23 cost analytics use only settled ledger entries, probes blocked
by the daily cap correctly add zero Strict Verification credits spent.

## Scope

This guardrail applies to Strict Verification escalations that use billing
reference type `auto_strict_verification`, including manually forced strict
verification within a managed run.

It does not change direct `provider_mode=strict` billing. Direct strict runs
remain explicit user-selected strict measurements and continue to use their
existing request-level prepaid-credit reservation.

## Migration

Schema revision:

```text
20260927_0019
```

adds nullable integer column:

```text
tenants.auto_strict_daily_credit_budget
```

Existing Workspaces migrate with `NULL`, preserving unlimited behavior until
an administrator explicitly enables the daily guardrail.
