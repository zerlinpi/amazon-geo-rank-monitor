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
    } <= tables
    inspector = inspect(create_engine(database_url))
    api_key_columns = {
        column["name"] for column in inspector.get_columns("api_keys")
    }
    assert "scopes" in api_key_columns
    rank_job_columns = {
        column["name"] for column in inspector.get_columns("rank_jobs")
    }
    assert {
        "available_at",
        "claimed_by",
        "lease_expires_at",
        "max_attempts",
    } <= rank_job_columns
