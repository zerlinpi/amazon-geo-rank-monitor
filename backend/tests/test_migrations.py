from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository


def test_alembic_baseline_creates_schema(tmp_path, monkeypatch) -> None:
    database = tmp_path / "migration.db"
    database_url = f"sqlite+pysqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(Config("alembic.ini"), "head")

    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {
        "tenants",
        "geo_profiles",
        "monitor_targets",
        "rank_jobs",
        "rank_runs",
        "credit_ledger_entries",
        "worker_heartbeats",
        "audit_events",
        "users",
        "workspace_memberships",
        "user_sessions",
        "workspace_invitations",
        "account_tokens",
        "auth_events",
        "mfa_recovery_codes",
        "trusted_devices",
        "workspace_sso_configs",
        "sso_login_transactions",
        "sso_identities",
        "workspace_scim_configs",
        "scim_groups",
        "scim_group_members",
        "rank_alert_rules",
        "rank_alert_events",
        "rank_alert_deliveries",
        "report_schedules",
        "report_deliveries",
        "serp_probe_cache",
        "serp_competitive_observations",
    } <= tables
    inspector = inspect(create_engine(database_url))
    api_key_columns = {
        column["name"] for column in inspector.get_columns("api_keys")
    }
    assert {"scopes", "last_used_ip", "usage_count"} <= api_key_columns
    audit_columns = {
        column["name"] for column in inspector.get_columns("audit_events")
    }
    assert {"user_id", "actor_type"} <= audit_columns
    user_columns = {
        column["name"] for column in inspector.get_columns("users")
    }
    assert {
        "email_verified_at",
        "failed_login_count",
        "locked_until",
        "last_login_at",
        "last_login_ip",
        "mfa_secret_encrypted",
        "mfa_enabled_at",
        "mfa_last_verified_at",
    } <= user_columns
    session_columns = {
        column["name"] for column in inspector.get_columns("user_sessions")
    }
    assert {
        "csrf_hash",
        "created_ip",
        "last_seen_ip",
        "user_agent",
        "mfa_authenticated_at",
        "auth_method",
        "sso_owner_id",
    } <= session_columns
    membership_columns = {
        column["name"]
        for column in inspector.get_columns("workspace_memberships")
    }
    assert {
        "suspended_at",
        "scim_managed",
        "scim_external_id",
        "updated_at",
    } <= membership_columns
    membership_constraints = {
        item["name"]
        for item in inspector.get_unique_constraints("workspace_memberships")
    }
    assert "uq_workspace_scim_external_id" in membership_constraints

    tenant_columns = {
        column["name"] for column in inspector.get_columns("tenants")
    }
    assert {
        "require_mfa",
        "auto_strict_enabled",
        "auto_strict_min_confidence",
        "auto_strict_max_probes_per_run",
        "auto_strict_daily_credit_budget",
    } <= tenant_columns
    token_columns = {
        column["name"] for column in inspector.get_columns("account_tokens")
    }
    assert {"details"} <= token_columns
    monitor_columns = {
        column["name"] for column in inspector.get_columns("monitor_targets")
    }
    assert {
        "auto_strict_enabled",
        "auto_strict_min_confidence",
        "auto_strict_max_probes_per_run",
    } <= monitor_columns
    rank_run_columns = {
        column["name"] for column in inspector.get_columns("rank_runs")
    }
    assert {"cache_hit_count", "verification_metadata"} <= rank_run_columns
    rank_observation_columns = {
        column["name"] for column in inspector.get_columns("rank_observations")
    }
    assert {"probe_source", "cache_age_seconds"} <= rank_observation_columns

    rank_job_columns = {
        column["name"] for column in inspector.get_columns("rank_jobs")
    }
    assert {
        "available_at",
        "claimed_by",
        "lease_expires_at",
        "max_attempts",
    } <= rank_job_columns


    alert_rule_columns = {
        column["name"] for column in inspector.get_columns("rank_alert_rules")
    }
    assert {
        "channels_encrypted",
        "cooldown_minutes",
        "deleted_at",
    } <= alert_rule_columns


def test_history_index_upgrade_and_downgrade_preserve_existing_runs(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'history-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "20260927_0020")
    engine = create_engine(database_url)
    # The historical baseline imports current models; simulate a deployed old schema.
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX IF EXISTS ix_rank_runs_owner_started_id")
    ranks = RankRepository(engine)
    run_id = ranks.create_run(
        owner_id="tenant-a", marketplace="amazon.com", keyword="trailer hitch",
        requested_probe_count=1,
    )

    command.upgrade(config, "head")
    indexes = {item["name"]: item for item in inspect(engine).get_indexes("rank_runs")}
    assert indexes["ix_rank_runs_owner_started_id"]["column_names"] == [
        "owner_id", "started_at", "id",
    ]
    assert ranks.get_run(run_id, owner_id="tenant-a")["keyword"] == "trailer hitch"
    command.downgrade(config, "20260927_0020")
    assert "ix_rank_runs_owner_started_id" not in {
        item["name"] for item in inspect(engine).get_indexes("rank_runs")
    }
    assert ranks.get_run(run_id, owner_id="tenant-a")["keyword"] == "trailer hitch"
    command.upgrade(config, "head")
    assert ranks.get_run(run_id, owner_id="tenant-a")["keyword"] == "trailer hitch"

def test_alert_baseline_index_upgrade_and_downgrade_preserve_jobs(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'alert-index-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "20260928_0021")
    engine = create_engine(database_url)
    jobs = JobRepository(engine)
    created = jobs.enqueue(
        owner_id="tenant-a",
        monitor_target_id="monitor-a",
        provider_mode="managed",
        request_payload={"keyword": "trailer hitch"},
    )
    index_name = "ix_rank_jobs_owner_monitor_status_run"
    assert index_name not in {
        item["name"] for item in inspect(engine).get_indexes("rank_jobs")
    }

    command.upgrade(config, "head")
    indexes = {
        item["name"]: item for item in inspect(engine).get_indexes("rank_jobs")
    }
    assert indexes[index_name]["column_names"] == [
        "owner_id",
        "monitor_target_id",
        "status",
        "run_id",
    ]
    with engine.connect() as connection:
        plan = connection.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT run_id FROM rank_jobs "
            "WHERE owner_id = ? AND monitor_target_id = ? AND status = ?",
            ("tenant-a", "monitor-a", "succeeded"),
        ).all()
    assert any(index_name in row[3] for row in plan)
    assert jobs.get(created["id"], owner_id="tenant-a")["monitor_target_id"] == (
        "monitor-a"
    )

    command.downgrade(config, "20260928_0021")
    assert index_name not in {
        item["name"] for item in inspect(engine).get_indexes("rank_jobs")
    }
    assert jobs.get(created["id"], owner_id="tenant-a")["status"] == "pending"
    command.upgrade(config, "head")
    assert index_name in {
        item["name"] for item in inspect(engine).get_indexes("rank_jobs")
    }
