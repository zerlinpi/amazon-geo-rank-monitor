from __future__ import annotations

import pytest

from amazon_geo_rank_monitor.config import AppSettings
from amazon_geo_rank_monitor.operations.readiness import run_staging_readiness


def settings(**overrides) -> AppSettings:
    values = {
        "session_cookie_secure": True,
        "public_web_url": "https://app.example.com",
        "sso_callback_url": "https://api.example.com/api/v1/auth/sso/callback",
        "stripe_success_url": "https://app.example.com/billing/success",
        "stripe_cancel_url": "https://app.example.com/billing",
        "cors_origins": "https://app.example.com",
        "smtp_host": "smtp.example.com",
        "smtp_from_email": "noreply@example.com",
        "stripe_secret_key": "sk_test_secret",
        "stripe_webhook_secret": "whsec_secret",
        "oxylabs_username": "managed-user",
        "oxylabs_password": "managed-secret",
        "residential_proxy_username": "proxy-user",
        "residential_proxy_password": "proxy-secret",
    }
    values.update(overrides)
    return AppSettings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_configuration_only_readiness_is_safe_and_passes() -> None:
    payload = await run_staging_readiness(settings())

    assert payload["status"] == "pass"
    assert payload["live"] is False
    assert payload["paid_provider_probes"] is False
    names = {item["name"] for item in payload["checks"]}
    assert "smtp_live" not in names
    assert "managed_provider_paid_probe" not in names


@pytest.mark.asyncio
async def test_live_readiness_uses_non_transactional_probes() -> None:
    calls = []

    def smtp_probe(_settings):
        calls.append("smtp")

    def stripe_probe(_settings):
        calls.append("stripe")

    payload = await run_staging_readiness(
        settings(),
        live=True,
        smtp_probe=smtp_probe,
        stripe_probe=stripe_probe,
    )

    assert payload["status"] == "pass"
    assert calls == ["smtp", "stripe"]
    assert {
        item["name"]: item["status"] for item in payload["checks"]
    }["smtp_live"] == "pass"


@pytest.mark.asyncio
async def test_paid_provider_probes_require_explicit_opt_in() -> None:
    calls = []

    async def managed_probe(_settings, **kwargs):
        calls.append(("managed", kwargs))

    async def strict_probe(_settings, **kwargs):
        calls.append(("strict", kwargs))

    await run_staging_readiness(
        settings(),
        managed_probe=managed_probe,
        strict_probe=strict_probe,
    )
    assert calls == []

    payload = await run_staging_readiness(
        settings(),
        paid_provider_probes=True,
        keyword="walking pad",
        postal_code="10001",
        managed_probe=managed_probe,
        strict_probe=strict_probe,
    )

    assert payload["status"] == "pass"
    assert calls == [
        ("managed", {"keyword": "walking pad", "postal_code": "10001"}),
        ("strict", {"keyword": "walking pad", "postal_code": "10001"}),
    ]


@pytest.mark.asyncio
async def test_upstream_failure_does_not_expose_exception_message() -> None:
    secret = "sk_live_should_never_appear"

    def stripe_probe(_settings):
        raise RuntimeError(f"provider rejected token {secret}")

    payload = await run_staging_readiness(
        settings(),
        live=True,
        smtp_probe=lambda _settings: None,
        stripe_probe=stripe_probe,
    )

    assert payload["status"] == "fail"
    rendered = str(payload)
    assert secret not in rendered
    stripe = next(
        item for item in payload["checks"] if item["name"] == "stripe_live"
    )
    assert stripe["detail"] == "failed (RuntimeError)"


@pytest.mark.asyncio
async def test_insecure_staging_configuration_fails_before_release() -> None:
    payload = await run_staging_readiness(
        settings(
            session_cookie_secure=False,
            public_web_url="http://localhost:5173",
            cors_origins="http://localhost:5173",
        )
    )

    assert payload["status"] == "fail"
    failed = {
        item["name"] for item in payload["checks"] if item["status"] == "fail"
    }
    assert "secure_session_cookie" in failed
    assert "public_web_https" in failed
    assert "cors_https_only" in failed
