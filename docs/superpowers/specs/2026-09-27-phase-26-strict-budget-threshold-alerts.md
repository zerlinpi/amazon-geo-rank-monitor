# Phase 26 — Strict Verification Daily Budget Threshold Alerts

## Goal

Turn the Phase 25 live Strict Verification daily budget status into proactive
operator alerts before the hard Phase 24 guardrail blocks new paid probes.

## Rule

A new Rank Alert rule type is available:

```text
strict_daily_budget_near_cap
```

The rule requires a percentage threshold from 1 through 100.

A completed managed Rank Run triggers the rule when the Workspace live UTC
daily Strict Verification budget reports:

```text
utilization_pct >= configured threshold
```

The alert is Workspace-wide. It does not use ASIN or Geo scope.

## Source of truth

The alert does not independently recalculate spend.

After Strict Verification work finishes, the verifier reads the existing
`BillingRepository.reference_budget_status` source used by the Phase 25 Team
and System Status views. The resulting live status is persisted into the Rank
Run verification metadata:

```json
{
  "daily_budget_status": {
    "billing_available": true,
    "window_start": "2026-09-27T00:00:00+00:00",
    "reset_at": "2026-09-28T00:00:00+00:00",
    "limit": 100,
    "settled_credits": 75,
    "reserved_credits": 10,
    "committed_credits": 85,
    "remaining_credits": 15,
    "utilization_pct": 85.0
  }
}
```

Unlimited workspaces do not trigger this alert because `limit=null`.

## Delivery and deduplication

The new rule reuses the existing Rank Alerts delivery path:

- email;
- generic webhook;
- Slack webhook;
- existing event history;
- existing cooldown suppression.

No new notification subsystem is introduced.

Operators can therefore create rules such as:

- warn at 80%;
- escalate at 95%;
- notify at 100%.

Cooldown remains the mechanism for suppressing repeated alerts from subsequent
runs during the same UTC day.

## UI

**Workspace → Alerts** exposes **Strict daily credit cap reaches N%**.

For this rule:

- the threshold control is labeled as daily budget utilization;
- maximum threshold is 100;
- ASIN scope is hidden;
- Geo scope is hidden;
- explanatory copy states that the rule is Workspace-wide.

## Failure behavior

If billing is unavailable, the cap is unlimited, or no live status was
persisted, the threshold rule does not fire.

The existing `strict_daily_budget_exhausted` probe-level rule remains
unchanged and still fires when a new strict reservation is actively blocked by
the hard daily guardrail.
