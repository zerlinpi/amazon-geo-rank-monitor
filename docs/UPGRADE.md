# Upgrade and rollback

1. Record the deployed Git SHA, image IDs, `alembic current`, environment version,
   and validate result. Take and test a backup using BACKUP_RESTORE.md.
2. Stop scheduler first, allow queued/running work to drain, then stop worker and
   API. Avoid lease recovery charging an in-flight probe during a rolling schema upgrade.
3. Fetch the reviewed target SHA; keep a named/tagged copy of previous images.
   Compare CHANGELOG.md and `.env.example` and retain existing encryption/pepper keys.
4. Build the target images. Run `docker compose run --rm migrate` exactly once,
   inspect the output, then `docker compose up -d --wait --wait-timeout 180`.
   Check readiness, heartbeats and a test account's history/analytics. Observe retries,
   latency, reservation balances and alert/report delivery before normal scheduling.

Phase 32 adds no migration; its single head is `20260928_0021`. Published revisions
are immutable. CI tests empty PostgreSQL→head, column parity with models and the
bounded `20260928_0021`→`20260927_0020`→head sequence while preserving an existing run.
The historical initial migration imports model metadata; its contents are unchanged.
CI guards fresh-schema behavior; future schema changes must use new revisions.

For a code-only rollback, stop scheduler/worker, redeploy the recorded previous
images/SHA with the same keys/database, and recheck readiness. Do not blindly
`alembic downgrade base`. Only use a documented, tested bounded downgrade when
required by an older code version and after a backup. The Phase 31 history index
can be downgraded to `20260927_0020` without deleting runs; do not use it as a general
rollback recipe for older schema changes. Restoring a DB backup also rewinds billing,
webhooks and jobs; reconcile externally paid Stripe events before restarting.

Dependency refreshes must regenerate `backend/requirements*.lock`, wrapper
`frontend/package-lock.json` and the exact upstream security patch as applicable,
then pass validate. Do not remove or weaken failing checks to publish a release.
