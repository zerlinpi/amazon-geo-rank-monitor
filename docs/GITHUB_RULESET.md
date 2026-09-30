# Main branch ruleset

The current connector can read rulesets and create/merge PRs, but exposes no ruleset
mutation endpoint. An empty ruleset list was observed during Phase 32. This document
is a required administrator action, not a claim that protection has been enabled.

In repository Settings → Rules → Rulesets, create an active branch ruleset targeting
`refs/heads/main` (include the default branch). Enable:

- Require a pull request before merging.
- Require conversation resolution.
- Require linear history; use squash or rebase merges.
- Block force pushes and branch deletion.
- Require the status check **validate** from GitHub Actions. Select the check emitted
  by the **Validate** workflow after its first run. Do not require path-filtered old
  `test`/`build` checks that may never be emitted for a PR.
- Require branches to be up to date before merging, according to team policy.
- Limit bypass privileges to documented emergency maintainers; do not add the agent
  or automation as a blanket bypass.

The aggregate validate job uses `always()` and requires all five dependencies to be
`success`, including E2E/security/Compose. Skipped/cancelled/failed jobs cannot pass.
The parent workflow runs on every PR with no path filters. If a merge queue is later
introduced, add `merge_group` to the parent triggers and validate the queue behavior.

Verify protection with a disposable PR containing a deliberate failing check;
confirm merging is blocked, then close it. Record the ruleset URL and verification
date in the operations record. Repository ownership/admin access is required.
