# Backup and restore

PostgreSQL holds tenants/users, auth hashes, encrypted MFA/SSO/SCIM settings,
geo profiles/monitors, jobs, runs/observations/snapshots, cache/competitor evidence,
billing ledger/payments/webhook IDs, alerts/reports and audit records. Back up all
of it as one consistent database. Redis holds short-lived rate-limit state and is
not the source of truth for jobs or credits.

Create a custom-format backup; store encrypted, access-controlled copies off-host
with timestamp, SHA, schema head and retention policy. These commands reference
container credentials without printing passwords:

```sh
mkdir -p backups
chmod 700 backups
docker compose exec -T postgres pg_dump -U amazon_geo_rank -d amazon_geo_rank -Fc > backups/agrm.dump
chmod 600 backups/agrm.dump
```

Back up `.env`/secret-manager versions separately, especially API/SCIM peppers and
MFA/SSO/alert/report encryption keys. Database-only restore cannot decrypt records
without the original keys. Never store these backups in this repository or CI artifacts.
Include TLS/DNS/reverse-proxy settings in operational recovery records.

Test restoration into an **isolated empty database**, with scheduler/worker stopped
and external provider/payment/email credentials disabled. Do not run these commands
against a live database:

```sh
docker compose exec -T postgres createdb -U amazon_geo_rank agrm_restore_check
docker compose exec -T postgres pg_restore -U amazon_geo_rank -d agrm_restore_check --exit-on-error < backups/agrm.dump
docker compose exec -T postgres psql -U amazon_geo_rank -d agrm_restore_check -c 'SELECT version_num FROM alembic_version'
```

Point an isolated application instance at that DB and verify tenant isolation, user
login, selected run evidence, row counts, ledger/reservation balances, and decryption
of settings without logging their values. Perform this drill before upgrades and
regularly thereafter; record actual recovery time and recovery-point age. Define
business RPO/RTO based on measured backup cadence, not assumptions.

For disaster recovery, stop ingestion and restore only after preserving the failed
DB for investigation. Reconcile jobs, credit reservations, already-paid checkouts,
webhook IDs and sent reports before restarting workers/scheduler. A restored older
snapshot must not replay paid credits or duplicate customer notifications. Never
`docker compose down --volumes` on a production deployment as an upgrade step.
