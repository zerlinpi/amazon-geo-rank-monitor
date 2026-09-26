from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


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
    assert {"require_mfa"} <= tenant_columns
    token_columns = {
        column["name"] for column in inspector.get_columns("account_tokens")
    }
    assert {"details"} <= token_columns
    rank_run_columns = {
        column["name"] for column in inspector.get_columns("rank_runs")
    }
    assert {"cache_hit_count"} <= rank_run_columns
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
