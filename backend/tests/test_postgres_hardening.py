"""Destructive only inside unique, newly-created test databases; never touches the URL's DB."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import make_url

from alembic import command
from amazon_geo_rank_monitor.repositories.alert_repository import AlertRepository
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
from amazon_geo_rank_monitor.repositories.job_repository import JobRepository
from amazon_geo_rank_monitor.repositories.models import Base, SerpProbeCacheRow, TenantRow
from amazon_geo_rank_monitor.repositories.probe_cache_repository import ProbeCacheRepository
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository
from amazon_geo_rank_monitor.repositories.report_repository import ReportRepository
from amazon_geo_rank_monitor.repositories.tenant_repository import TenantRepository

pytestmark = pytest.mark.skipif(
    not os.getenv("POSTGRES_TEST_URL"), reason="POSTGRES_TEST_URL unset"
)


@pytest.fixture
def database():
    url = make_url(os.environ["POSTGRES_TEST_URL"])
    name = f"agrm_phase32_{uuid4().hex}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = create_engine(url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture
def schema(database):
    Base.metadata.create_all(database)
    with database.begin() as connection:
        connection.execute(TenantRow.__table__.insert().values(id="owner", name="Fixture owner"))
    return database


def race(action, count=8):
    gate = Barrier(count)

    def run(index):
        gate.wait(timeout=10)
        return action(index)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run, range(count)))


def test_fresh_postgres_migration_schema_and_bounded_rollback(database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database.url.render_as_string(hide_password=False))
    config = Config("alembic.ini")
    assert ScriptDirectory.from_config(config).get_heads() == ["20260928_0021"]
    command.upgrade(config, "head")
    inspector = inspect(database)
    for table in Base.metadata.sorted_tables:
        assert {c.name for c in table.columns} == {
            c["name"] for c in inspector.get_columns(table.name)
        }, table.name
    ranks = RankRepository(database)
    run_id = ranks.create_run(
        owner_id="migration-owner",
        marketplace="amazon.com",
        keyword="preserve me",
        requested_probe_count=1,
    )
    command.downgrade(config, "20260927_0020")
    assert "ix_rank_runs_owner_started_id" not in {
        i["name"] for i in inspect(database).get_indexes("rank_runs")
    }
    command.upgrade(config, "head")
    assert ranks.get_run(run_id)["keyword"] == "preserve me"
    assert "ix_rank_runs_owner_started_id" in {
        i["name"] for i in inspect(database).get_indexes("rank_runs")
    }


def test_postgres_duplicate_job_and_report_delivery_are_singletons(schema):
    ids = race(
        lambda _: JobRepository(schema).enqueue(
            owner_id="owner",
            provider_mode="managed",
            request_payload={},
            job_id="cron-slot",
        )["id"]
    )
    assert set(ids) == {"cron-slot"}
    reports = ReportRepository(schema)
    schedule = reports.create_schedule(
        owner_id="owner",
        name="Weekly",
        monitor_target_ids=[],
        recipients_encrypted="fixture",
        schedule="0 0 * * *",
        lookback_hours=24,
        include_csv=False,
        enabled=True,
    )
    now = datetime.now(UTC)
    deliveries = race(
        lambda _: ReportRepository(schema).reserve_delivery(
            owner_id="owner",
            schedule_id=schedule["id"],
            scheduled_for=now,
            subject="Fixture",
            recipient_count=1,
        )
    )
    assert sum(item is not None for item in deliveries) == 1


def test_postgres_alert_cooldown_is_atomic_across_workers(schema):
    alerts = AlertRepository(schema)
    rule = alerts.create_rule(
        owner_id="owner",
        monitor_target_id=None,
        name="Missing",
        rule_type="not_found",
        threshold=None,
        asin=None,
        geo_profile_id=None,
        channels_encrypted="fixture",
        cooldown_minutes=60,
        enabled=True,
    )
    events = race(
        lambda index: AlertRepository(schema).create_event_if_not_cooling(
            owner_id="owner",
            rule_id=rule["id"],
            monitor_target_id="monitor",
            run_id=f"run-{index}",
            asin="B0TARGET01",
            geo_profile_id="ny",
            event_type="not_found",
            fingerprint=f"fingerprint-{index}",
            previous_value=None,
            current_value=None,
            details={},
            cooldown_minutes=60,
        )
    )
    assert sum(item is not None for item in events) == 1


def test_postgres_webhook_event_idempotency_is_atomic(schema):
    results = race(
        lambda _: BillingRepository(schema).record_webhook_event(
            provider_event_id="evt_fixture",
            event_type="ignored",
            payload_hash="fixture",
        )
    )
    assert results.count(True) == 1
    assert results.count(False) == 7


def test_postgres_duplicate_paid_webhooks_credit_once(schema):
    owner = TenantRepository(schema).create_tenant("Billing fixture")["id"]
    billing = BillingRepository(schema)
    billing.upsert_credit_pack(
        pack_id="fixture", name="Fixture", credits=50, amount_minor=100, currency="usd"
    )
    payment = billing.create_payment(owner_id=owner, credit_pack_id="fixture")
    results = race(
        lambda _: BillingRepository(schema).apply_paid_checkout(
            provider_event_id="evt_paid",
            event_type="checkout.session.completed",
            payload_hash="same",
            payment_id=payment["id"],
            session_id="cs_fixture",
            payment_intent_id="pi_fixture",
        )
    )
    assert all(result["status"] == "paid" for result in results)
    assert billing.get_balance(owner) == {"balance": 50, "reserved": 0, "available": 50}


def test_postgres_cache_parallel_upsert_and_hit_count(schema):
    now = datetime.now(UTC)
    values = dict(
        owner_id="owner",
        cache_key="key",
        provider_mode="managed",
        provider_name="fixture",
        verification_level="managed",
        marketplace="amazon.com",
        keyword="trailer hitch",
        geo_profile_id="ny",
        device="desktop",
        search_depth=100,
        identity_payload={},
        result_payload={},
        fetched_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    race(lambda _: ProbeCacheRepository(schema).put(**values))
    race(
        lambda _: ProbeCacheRepository(schema).get_fresh(owner_id="owner", cache_key="key", now=now)
    )
    with schema.connect() as connection:
        assert connection.scalar(select(SerpProbeCacheRow.hit_count)) == 8
    # A slow upstream response must not overwrite a newer, fresh response.
    ProbeCacheRepository(schema).put(
        **{**values, "fetched_at": now - timedelta(minutes=1), "result_payload": {"stale": True}}
    )
    assert (
        ProbeCacheRepository(schema).get_fresh(
            owner_id="owner",
            cache_key="key",
            now=now,
        )["result_payload"]
        == {}
    )
