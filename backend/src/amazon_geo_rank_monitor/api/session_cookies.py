from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Response


def session_payload(services, session) -> dict:
    return {
        "expires_at": session.expires_at,
        **services.accounts.profile(session.principal),
    }


def set_session_cookies(response: Response, services, session) -> None:
    same_site = services.session_cookie_samesite.lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    now = datetime.now(UTC)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    max_age = max(int((expires_at - now).total_seconds()), 1)

    response.set_cookie(
        key=services.session_cookie_name,
        value=session.plaintext,
        max_age=max_age,
        expires=expires_at,
        path="/",
        secure=services.session_cookie_secure,
        httponly=True,
        samesite=same_site,
    )
    response.set_cookie(
        key=services.csrf_cookie_name,
        value=session.csrf_token,
        max_age=max_age,
        expires=expires_at,
        path="/",
        secure=services.session_cookie_secure,
        httponly=False,
        samesite=same_site,
    )


def clear_session_cookies(response: Response, services) -> None:
    same_site = services.session_cookie_samesite.lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    for key in (services.session_cookie_name, services.csrf_cookie_name):
        response.delete_cookie(
            key=key,
            path="/",
            secure=services.session_cookie_secure,
            samesite=same_site,
        )


def set_trusted_device_cookie(
    response: Response,
    services,
    *,
    token: str,
    expires_at: datetime,
) -> None:
    same_site = services.session_cookie_samesite.lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    now = datetime.now(UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    max_age = max(int((expires_at - now).total_seconds()), 1)
    response.set_cookie(
        key=services.trusted_device_cookie_name,
        value=token,
        max_age=max_age,
        expires=expires_at,
        path="/",
        secure=services.session_cookie_secure,
        httponly=True,
        samesite=same_site,
    )


def clear_trusted_device_cookie(response: Response, services) -> None:
    same_site = services.session_cookie_samesite.lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    response.delete_cookie(
        key=services.trusted_device_cookie_name,
        path="/",
        secure=services.session_cookie_secure,
        samesite=same_site,
    )
