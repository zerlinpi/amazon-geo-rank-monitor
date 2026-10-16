from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_credit_audit_upgrade_and_rollback_preserve_old_balances(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'credit-upgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261008_0022")
    engine = create_engine(url)
    # Historical migrations import current models; simulate the previously deployed table.
    with engine.begin() as connection:
        if "details" in {c["name"] for c in inspect(engine).get_columns("credit_ledger_entries")}:
            connection.exec_driver_sql("ALTER TABLE credit_ledger_entries DROP COLUMN details")
        connection.exec_driver_sql(
            "INSERT INTO tenants (id, name, created_at, require_mfa, "
            "auto_strict_daily_budget_pacing_enabled) "
            "VALUES ('owner', 'Owner', CURRENT_TIMESTAMP, 0, 0)"
        )
        connection.exec_driver_sql(
            "INSERT INTO credit_accounts (owner_id, balance, reserved, updated_at) "
            "VALUES ('owner', 80, 5, CURRENT_TIMESTAMP)"
        )
    command.upgrade(config, "head")
    assert "details" in {c["name"] for c in inspect(engine).get_columns("credit_ledger_entries")}
    command.downgrade(config, "20261008_0022")
    with engine.connect() as connection:
        assert tuple(connection.exec_driver_sql(
            "SELECT balance, reserved FROM credit_accounts WHERE owner_id='owner'"
        ).one()) == (80, 5)
    command.upgrade(config, "head")
    engine.dispose()
