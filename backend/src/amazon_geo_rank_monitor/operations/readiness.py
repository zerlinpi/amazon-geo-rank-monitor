from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Awaitable, Callable
from urllib.parse import urlparse

from amazon_geo_rank_monitor.config import (
    AppSettings,
    build_oxylabs_provider,
    build_residential_proxy_factory,
)
from amazon_geo_rank_monitor.domain.models import GeoProfile
from amazon_geo_rank_monitor.providers.playwright_amazon import (
    PlaywrightAmazonBrowserClient,
)
from amazon_geo_rank_monitor.providers.strict_browser import StrictBrowserRankProvider


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def _result(name: str, passed: bool, detail: str) -> ReadinessCheck:
    return ReadinessCheck(
        name=name,
        status="pass" if passed else "fail",
        detail=detail,
    )


def _exception_detail(exc: Exception) -> str:
    # Upstream exception text can contain hosts, usernames or provider payloads.
    # Staging-readiness output is intentionally safe to retain in CI logs.
    return f"failed ({type(exc).__name__})"


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname)


def configuration_checks(settings: AppSettings) -> list[ReadinessCheck]:
    cors_origins = settings.cors_origin_list
    return [
        _result(
            "secure_session_cookie",
            settings.session_cookie_secure,
            "secure cookie enabled"
            if settings.session_cookie_secure
            else "SESSION_COOKIE_SECURE must be true",
        ),
        _result(
            "public_web_https",
            _is_https_url(settings.public_web_url),
            "HTTPS public web URL configured"
            if _is_https_url(settings.public_web_url)
            else "PUBLIC_WEB_URL must use HTTPS",
        ),
        _result(
            "sso_callback_https",
            _is_https_url(settings.sso_callback_url),
            "HTTPS SSO callback configured"
            if _is_https_url(settings.sso_callback_url)
            else "SSO_CALLBACK_URL must use HTTPS",
        ),
        _result(
            "stripe_return_urls_https",
            _is_https_url(settings.stripe_success_url)
            and _is_https_url(settings.stripe_cancel_url),
            "HTTPS Stripe return URLs configured"
            if (
                _is_https_url(settings.stripe_success_url)
                and _is_https_url(settings.stripe_cancel_url)
            )
            else "STRIPE_SUCCESS_URL and STRIPE_CANCEL_URL must use HTTPS",
        ),
        _result(
            "cors_https_only",
            bool(cors_origins)
            and all(_is_https_url(origin) for origin in cors_origins),
            "CORS origins use HTTPS"
            if (
                bool(cors_origins)
                and all(_is_https_url(origin) for origin in cors_origins)
            )
            else "CORS_ORIGINS must contain only HTTPS origins",
        ),
        _result(
            "smtp_configured",
            bool(settings.smtp_host and settings.smtp_from_email),
            "SMTP host and sender configured"
            if settings.smtp_host and settings.smtp_from_email
            else "SMTP_HOST and SMTP_FROM_EMAIL are required",
        ),
        _result(
            "stripe_configured",
            bool(settings.stripe_secret_key and settings.stripe_webhook_secret),
            "Stripe API and webhook credentials configured"
            if settings.stripe_secret_key and settings.stripe_webhook_secret
            else "STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are required",
        ),
        _result(
            "managed_provider_configured",
            bool(settings.oxylabs_username and settings.oxylabs_password),
            "managed provider credentials configured"
            if settings.oxylabs_username and settings.oxylabs_password
            else "OXYLABS_USERNAME and OXYLABS_PASSWORD are required",
        ),
        _result(
            "strict_proxy_configured",
            bool(
                settings.residential_proxy_username
                and settings.residential_proxy_password
            ),
            "strict residential proxy credentials configured"
            if (
                settings.residential_proxy_username
                and settings.residential_proxy_password
            )
            else (
                "RESIDENTIAL_PROXY_USERNAME and "
                "RESIDENTIAL_PROXY_PASSWORD are required"
            ),
        ),
    ]


def _smtp_live_probe(settings: AppSettings) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise RuntimeError("SMTP is not configured")
    with smtplib.SMTP(
        settings.smtp_host,
        settings.smtp_port,
        timeout=15.0,
    ) as client:
        client.ehlo()
        if settings.smtp_starttls:
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if settings.smtp_username:
            client.login(
                settings.smtp_username,
                settings.smtp_password or "",
            )
        client.noop()


def _stripe_live_probe(settings: AppSettings) -> None:
    if not settings.stripe_secret_key:
        raise RuntimeError("Stripe is not configured")
    import stripe

    stripe.api_key = settings.stripe_secret_key
    stripe.Balance.retrieve()


def _staging_geo(postal_code: str) -> GeoProfile:
    return GeoProfile(
        id="staging-readiness",
        name="Staging readiness",
        marketplace="amazon.com",
        ip_country="US",
        ip_postal_code=postal_code,
        delivery_country="US",
        delivery_postal_code=postal_code,
        device="desktop",
        weight=Decimal("1"),
    )


async def _managed_paid_probe(
    settings: AppSettings,
    *,
    keyword: str,
    postal_code: str,
) -> None:
    provider = build_oxylabs_provider(settings)
    await provider.search(
        marketplace="amazon.com",
        keyword=keyword,
        geo_profile=_staging_geo(postal_code),
        device="desktop",
        search_depth=1,
    )


async def _strict_paid_probe(
    settings: AppSettings,
    *,
    keyword: str,
    postal_code: str,
) -> None:
    proxy_factory = build_residential_proxy_factory(settings)
    provider = StrictBrowserRankProvider(
        proxy_factory=proxy_factory,
        browser_client_factory=lambda proxy: PlaywrightAmazonBrowserClient(proxy),
    )
    await provider.search(
        marketplace="amazon.com",
        keyword=keyword,
        geo_profile=_staging_geo(postal_code),
        device="desktop",
        search_depth=1,
    )


SyncProbe = Callable[[AppSettings], None]
PaidProbe = Callable[..., Awaitable[None]]


async def run_staging_readiness(
    settings: AppSettings,
    *,
    live: bool = False,
    paid_provider_probes: bool = False,
    keyword: str = "walking pad",
    postal_code: str = "10001",
    smtp_probe: SyncProbe | None = None,
    stripe_probe: SyncProbe | None = None,
    managed_probe: PaidProbe | None = None,
    strict_probe: PaidProbe | None = None,
) -> dict:
    checks = configuration_checks(settings)
    if live:
        for name, probe in (
            ("smtp_live", smtp_probe or _smtp_live_probe),
            ("stripe_live", stripe_probe or _stripe_live_probe),
        ):
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(probe, settings),
                    timeout=30.0,
                )
            except Exception as exc:
                checks.append(_result(name, False, _exception_detail(exc)))
            else:
                checks.append(_result(name, True, "live authentication succeeded"))

    if paid_provider_probes:
        if len(postal_code) != 5 or not postal_code.isdigit():
            checks.append(
                _result(
                    "paid_probe_postal_code",
                    False,
                    "paid provider probe ZIP must be exactly five digits",
                )
            )
        elif not keyword.strip():
            checks.append(
                _result(
                    "paid_probe_keyword",
                    False,
                    "paid provider probe keyword must not be empty",
                )
            )
        else:
            for name, probe in (
                (
                    "managed_provider_paid_probe",
                    managed_probe or _managed_paid_probe,
                ),
                (
                    "strict_provider_paid_probe",
                    strict_probe or _strict_paid_probe,
                ),
            ):
                try:
                    await asyncio.wait_for(
                        probe(
                            settings,
                            keyword=keyword.strip(),
                            postal_code=postal_code,
                        ),
                        timeout=180.0,
                    )
                except Exception as exc:
                    checks.append(_result(name, False, _exception_detail(exc)))
                else:
                    checks.append(
                        _result(
                            name,
                            True,
                            "controlled paid staging probe succeeded",
                        )
                    )

    payload = {
        "status": "pass" if all(item.passed for item in checks) else "fail",
        "live": live,
        "paid_provider_probes": paid_provider_probes,
        "checks": [asdict(item) for item in checks],
    }
    return payload
