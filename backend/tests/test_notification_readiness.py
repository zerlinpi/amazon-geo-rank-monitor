"""Email configuration must never masquerade as successful delivery."""

import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from test_account_recovery import build_client as build_account_client
from test_account_recovery import register
from test_alerts import ASIN, GEO_ID, MONITOR_ID, OWNER_ID, build_service, completed_jobs, geo_run
from test_analytics_reports import build_stack
from test_api_hardening import auth_for, build_client

from amazon_geo_rank_monitor.api.app import create_app
from amazon_geo_rank_monitor.config import AppSettings
from amazon_geo_rank_monitor.notifications.email import ConsoleEmailSender
from amazon_geo_rank_monitor.runtime import build_services


def test_unconfigured_alert_email_fails_without_blocking_other_channels():
    service, _ = build_service(
        runs={"current": geo_run("current", found=False, effective_rank=101)},
        jobs=completed_jobs("current"),
        allowed_hosts=["hooks.example.com"],
    )
    service._email = ConsoleEmailSender()
    service.create_rule(
        owner_id=OWNER_ID, monitor_target_id=MONITOR_ID, name="Missing product",
        rule_type="geo_not_found", threshold=None, asin=ASIN, geo_profile_id=GEO_ID,
        channels={
            "emails": ["fixture@example.com"],
            "webhook_url": "https://hooks.example.com/notify",
        },
        cooldown_minutes=0,
    )
    service.evaluate_run(owner_id=OWNER_ID, monitor_target_id=MONITOR_ID, run_id="current")

    deliveries = {
        row["channel_type"]: row
        for row in service.list_events(owner_id=OWNER_ID)[0]["deliveries"]
    }
    assert deliveries["email"]["status"] == "failed"
    assert deliveries["email"]["error"] == "Email delivery is not configured"
    assert deliveries["webhook"]["status"] == "sent"


def test_unconfigured_report_has_zero_sent_recipients_and_remains_idempotent():
    engine, _, _, reports, _ = build_stack()
    reports._email = ConsoleEmailSender()
    schedule = reports.create_schedule(
        owner_id=OWNER_ID, name="Weekly review", monitor_target_ids=[MONITOR_ID],
        recipients=["fixture@example.com"], schedule="0 9 * * 1",
        lookback_hours=168, include_csv=True,
    )
    scheduled_for = datetime.now(UTC).replace(second=0, microsecond=0)
    delivery = reports.dispatch_schedule(
        owner_id=OWNER_ID, schedule_id=schedule["id"], scheduled_for=scheduled_for,
    )
    assert delivery["status"] == "failed"
    assert delivery["sent_count"] == 0
    assert delivery["error"] == "Email delivery is not configured"
    assert reports.dispatch_schedule(
        owner_id=OWNER_ID, schedule_id=schedule["id"], scheduled_for=scheduled_for,
    ) is None
    engine.dispose()


def test_unconfigured_account_mail_preserves_recovery_privacy(caplog):
    client, services, _ = build_account_client()
    services.accounts._email_sender = ConsoleEmailSender()
    with caplog.at_level(logging.INFO):
        registered = register(client)
        existing = client.post(
            "/api/v1/auth/forgot-password", json={"email": "owner@example.com"},
        )
        missing = client.post(
            "/api/v1/auth/forgot-password", json={"email": "missing@example.com"},
        )
    assert registered["user"]["email_verified"] is False
    assert existing.status_code == missing.status_code == 202
    assert existing.json() == missing.json()
    assert "token=" not in caplog.text
    assert "agrv_" not in caplog.text
    assert "agrr_" not in caplog.text


def test_notification_status_requires_authenticated_monitor_read_scope():
    client, _, tenants, keys = build_client()
    assert client.get("/api/v1/notifications/status").status_code == 401
    tenant, _ = auth_for(tenants, keys, "Status reader")
    restricted = keys.create(owner_id=tenant["id"], name="Billing only", scopes=["billing:read"])
    response = client.get(
        "/api/v1/notifications/status", headers={"X-API-Key": restricted.plaintext},
    )
    assert response.status_code == 403
    reader = keys.create(owner_id=tenant["id"], name="Reader", scopes=["monitors:read"])
    response = client.get(
        "/api/v1/notifications/status", headers={"X-API-Key": reader.plaintext},
    )
    assert response.status_code == 200
    assert response.json() == {"email": {"configured": False}}


@pytest.mark.parametrize("configured", [False, True])
def test_runtime_notification_status_is_configuration_only(tmp_path, monkeypatch, configured):
    def unexpected_smtp(*args, **kwargs):
        pytest.fail("Reading configuration must not open an SMTP connection")

    monkeypatch.setattr("smtplib.SMTP", unexpected_smtp)
    settings = AppSettings(
        _env_file=None, database_url=f"sqlite+pysqlite:///{tmp_path / 'status.db'}",
        api_key_pepper="notification-fixture", auto_create_schema=True, redis_url=None,
        oxylabs_username=None, oxylabs_password=None, residential_proxy_username=None,
        residential_proxy_password=None, stripe_secret_key=None,
        smtp_host="private-smtp.example.com" if configured else None,
        smtp_from_email="private-sender@example.com", smtp_username="private-user",
        smtp_password="private-password", auto_strict_verification_enabled=False,
    )
    services = build_services(settings)
    _, headers = auth_for(services.tenant_repository, services.api_keys, "Status")
    with TestClient(create_app(services)) as client:
        response = client.get("/api/v1/notifications/status", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"email": {"configured": configured}}
    services.database_engine.dispose()
