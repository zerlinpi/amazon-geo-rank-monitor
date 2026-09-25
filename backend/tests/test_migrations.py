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
    } <= session_columns
    tenant_columns = {
        column["name"] for column in inspector.get_columns("tenants")
    }
    assert {"require_mfa"} <= tenant_columns
    token_columns = {
        column["name"] for column in inspector.get_columns("account_tokens")
    }
    assert {"details"} <= token_columns
    rank_job_columns = {
        column["name"] for column in inspector.get_columns("rank_jobs")
    }
    assert {
        "available_at",
        "claimed_by",
        "lease_expires_at",
        "max_attempts",
    } <= rank_job_columns
