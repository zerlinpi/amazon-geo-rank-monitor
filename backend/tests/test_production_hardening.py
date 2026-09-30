import csv
import logging
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_account_recovery import build_client as build_account_client
from test_alerts import ASIN, GEO_ID, MONITOR_ID, OWNER_ID, build_service, completed_jobs, geo_run
from test_analytics_reports import build_stack
from test_api_hardening import build_client

from amazon_geo_rank_monitor.api.app import create_app
from amazon_geo_rank_monitor.api.rate_limit import (
    FixedWindowRateLimiter,
    RedisWindowRateLimiter,
    ResilientRateLimiter,
)
from amazon_geo_rank_monitor.notifications.email import ConsoleEmailSender
from amazon_geo_rank_monitor.repositories.models import RankObservationRow
from amazon_geo_rank_monitor.repositories.rank_repository import RankRepository


def test_strict_evidence_counts_once_in_geo_summary_and_export():
    engine, analytics, _, _, _ = build_stack()
    with Session(engine) as session:
        session.add(RankObservationRow(
            rank_run_id="run-1", asin=ASIN, geo_profile_id=GEO_ID,
            provider="strict_test", verification_level="strict",
            status="success_not_found", found=False, organic_rank=None,
            effective_rank=101, observed_at=datetime.now(UTC),
        ))
        session.commit()
    summary = analytics.summary(owner_id=OWNER_ID, monitor_target_id=MONITOR_ID)
    geo = summary["geos"][0]
    assert geo["observation_count"] == 2
    assert geo["average_effective_rank"] == Decimal("54.5")
    assert geo["found_rate"] == Decimal("0.5")
    content, _ = analytics.export_csv(
        owner_id=OWNER_ID, monitor_target_id=MONITOR_ID, granularity="geo",
    )
    rows = list(csv.DictReader(StringIO(content)))
    assert [(row["run_id"], row["verification_level"]) for row in rows] == [
        ("run-1", "strict"), ("run-2", "managed"),
    ]
    assert len(RankRepository(engine).get_run("run-1", owner_id=OWNER_ID)["observations"]) == 2


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("rule_type", ["geo_not_found", "geo_rank_above"])
def test_successful_strict_result_prevents_obsolete_managed_geo_alert(rule_type, reverse):
    run = geo_run("current", found=False, effective_rank=101)
    strict = dict(geo_run("current", found=True, effective_rank=3)["observations"][0],
                  verification_level="strict", status="success_found")
    run["observations"].append(strict)
    if reverse:
        run["observations"].reverse()
    service, mailer = build_service(runs={"current": run}, jobs=completed_jobs("current"))
    service.create_rule(
        owner_id=OWNER_ID, monitor_target_id=MONITOR_ID, name="Geo regression",
        rule_type=rule_type, threshold=Decimal("50") if rule_type == "geo_rank_above" else None,
        asin=ASIN, geo_profile_id=GEO_ID, channels={"emails": ["fixture@example.com"]},
        cooldown_minutes=0,
    )
    assert service.evaluate_run(
        owner_id=OWNER_ID, monitor_target_id=MONITOR_ID, run_id="current",
    ) == []
    assert mailer.messages == []
    assert len(run["observations"]) == 2


def test_console_email_never_logs_authentication_links(caplog):
    with caplog.at_level(logging.INFO):
        ConsoleEmailSender().send(
            to="fixture@example.com", subject="Reset your password",
            text="https://example.com/reset?token=secret-reset-token",
        )
    assert "secret-reset-token" not in caplog.text
    assert "https://example.com/reset" not in caplog.text


class UnavailableRedis:
    def ping(self):
        raise ConnectionError("redis unavailable")


def test_readiness_reports_configured_redis_outage_without_affecting_liveness():
    _, services, _, _ = build_client()
    services.rate_limiter = ResilientRateLimiter(
        primary=RedisWindowRateLimiter(
            redis_url="redis://unused", requests_per_minute=120, client=UnavailableRedis(),
        ),
        fallback=FixedWindowRateLimiter(requests_per_minute=120),
    )
    client = TestClient(create_app(services))
    assert client.get("/health").status_code == 200
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["redis"] == "unavailable"


def test_failed_webhook_delivery_does_not_expose_secret_url():
    service, _ = build_service(
        runs={"current": geo_run("current", found=False, effective_rank=101)},
        jobs=completed_jobs("current"), allowed_hosts=["alerts.example.com"],
        handler=lambda request: httpx.Response(500),
    )
    service.create_rule(
        owner_id=OWNER_ID, monitor_target_id=MONITOR_ID, name="Webhook failure",
        rule_type="geo_not_found", threshold=None, asin=ASIN, geo_profile_id=GEO_ID,
        channels={"webhook_url": "https://alerts.example.com/secret-hook-token"},
        cooldown_minutes=0,
    )
    service.evaluate_run(owner_id=OWNER_ID, monitor_target_id=MONITOR_ID, run_id="current")
    delivery = service.list_events(owner_id=OWNER_ID)[0]["deliveries"][0]
    assert delivery["status"] == "failed"
    assert "secret-hook-token" not in str(delivery)
    assert "500" in delivery["error"]


def test_smtp_exception_does_not_leak_reset_token_into_logs(caplog):
    client, services, _ = build_account_client()
    class FailingEmail:
        def send(self, **message):
            raise RuntimeError("SMTP rejected " + message["text"])
    services.accounts._email_sender = FailingEmail()
    with caplog.at_level(logging.WARNING):
        response = client.post("/api/v1/auth/register", json={
            "email": "fixture@example.com", "password": "fixture-password-only",
            "display_name": "Fixture", "workspace_name": "Fixture workspace",
        })
    assert response.status_code == 201
    assert "token=" not in caplog.text
    assert "SMTP rejected" not in caplog.text


def test_alert_smtp_failure_does_not_store_exception_secrets():
    service, mailer = build_service(
        runs={"current": geo_run("current", found=False, effective_rank=101)},
        jobs=completed_jobs("current"),
    )

    def fail(**message):
        raise RuntimeError("SMTP rejected private-smtp-password")

    mailer.send = fail
    service.create_rule(
        owner_id=OWNER_ID, monitor_target_id=MONITOR_ID, name="Mail failure",
        rule_type="geo_not_found", threshold=None, asin=ASIN, geo_profile_id=GEO_ID,
        channels={"emails": ["fixture@example.com"]}, cooldown_minutes=0,
    )
    service.evaluate_run(owner_id=OWNER_ID, monitor_target_id=MONITOR_ID, run_id="current")
    delivery = service.list_events(owner_id=OWNER_ID)[0]["deliveries"][0]
    assert delivery["status"] == "failed"
    assert "private-smtp-password" not in str(delivery)
    assert "RuntimeError" in delivery["error"]


def test_slow_cache_write_cannot_replace_a_newer_result(tmp_path):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine

    from amazon_geo_rank_monitor.repositories.models import Base
    from amazon_geo_rank_monitor.repositories.probe_cache_repository import ProbeCacheRepository

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'cache.db'}")
    Base.metadata.create_all(engine)
    cache = ProbeCacheRepository(engine)
    now = datetime.now(UTC)
    values = dict(
        owner_id="owner", cache_key="key", provider_mode="managed", provider_name="fixture",
        verification_level="managed", marketplace="amazon.com", keyword="trailer hitch",
        geo_profile_id="ny", device="desktop", search_depth=100, identity_payload={},
        result_payload={"newest": True}, fetched_at=now, expires_at=now + timedelta(minutes=5),
    )
    cache.put(**values)
    cache.put(**{**values, "fetched_at": now - timedelta(minutes=1), "result_payload": {}})
    assert cache.get_fresh(owner_id="owner", cache_key="key", now=now)["result_payload"] == {
        "newest": True,
    }
    engine.dispose()


def test_parallel_ignored_webhooks_are_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy import create_engine, event

    from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository
    from amazon_geo_rank_monitor.repositories.models import Base

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'events.db'}")
    Base.metadata.create_all(engine)
    gate = Barrier(8)

    @event.listens_for(engine, "after_cursor_execute")
    def simultaneous_reads(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT webhook_events."):
            gate.wait(timeout=10)

    def record(_):
        return BillingRepository(engine).record_webhook_event(
            provider_event_id="evt_fixture", event_type="ignored", payload_hash="fixture",
        )

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(record, range(8)))
        assert results.count(True) == 1
        assert results.count(False) == 7
    finally:
        engine.dispose()


def test_unexpected_api_error_is_safe_json_with_request_id(caplog):
    original = build_client()[0]

    @original.app.get("/fixture-failure")
    def failure():
        raise RuntimeError("private-upstream-token")

    with TestClient(original.app, raise_server_exceptions=False) as client:
        response = client.get("/fixture-failure", headers={"X-Request-ID": "failure-fixture"})
    assert response.status_code == 500
    assert response.headers.get("X-Request-ID") == "failure-fixture"
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private-upstream-token" not in response.text + caplog.text


async def test_provider_errors_do_not_store_upstream_credentials():
    from test_oxylabs_provider import FakeAmazonClient, FakeClient, geo

    from amazon_geo_rank_monitor.domain.errors import ProviderUnavailableError
    from amazon_geo_rank_monitor.providers.oxylabs import OxylabsRankProvider

    provider = OxylabsRankProvider(client=FakeClient(FakeAmazonClient(
        error=RuntimeError("proxy password private-upstream-token"),
    )))
    with pytest.raises(ProviderUnavailableError) as caught:
        await provider.search(marketplace="amazon.com", keyword="hitch", geo_profile=geo(),
                              device="desktop", search_depth=100)
    assert "private-upstream-token" not in str(caught.value)
