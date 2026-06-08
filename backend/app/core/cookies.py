"""Auth cookie names + helpers.

Two cookies back the cookie-auth flow:

* **refresh** (``sentinelai_refresh``) — the long-lived secret. ``httpOnly`` so
  JS can never read it, ``Secure``/``SameSite`` per config, and path-scoped to
  ``/api/v1/auth`` so it is sent *only* to the auth endpoints that need it.
* **csrf** (``sentinelai_csrf``) — readable by the frontend (not ``httpOnly``);
  echoed back in the ``X-CSRF-Token`` header for the double-submit CSRF check.

Production defaults are ``Secure``; local non-HTTPS dev sets
``SENTINEL_AUTH_COOKIE_SECURE=false`` (browsers drop Secure cookies over http).
"""

from __future__ import annotations

import secrets

from fastapi import Response

from app.core.config import Settings

REFRESH_COOKIE = "sentinelai_refresh"
CSRF_COOKIE = "sentinelai_csrf"
# Optional: an access-token cookie is supported on read (deps) but not set by
# default — our SPA keeps the access token in memory and sends it as a Bearer.
ACCESS_COOKIE = "sentinelai_access"

CSRF_HEADER = "x-csrf-token"

# The refresh cookie is only ever sent to the auth router.
REFRESH_COOKIE_PATH = "/api/v1/auth"

# Cookie names whose presence marks a request as "cookie-authenticated" (and
# therefore subject to CSRF on unsafe methods).
AUTH_COOKIE_NAMES = frozenset({REFRESH_COOKIE, ACCESS_COOKIE})


def _samesite(settings: Settings) -> str:
    value = (settings.auth_cookie_samesite or "lax").strip().lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_refresh_cookie(response: Response, settings: Settings, token: str, *, max_age: int) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=_samesite(settings),
        domain=settings.auth_cookie_domain,
        path=REFRESH_COOKIE_PATH,
    )


def set_csrf_cookie(response: Response, settings: Settings, token: str, *, max_age: int) -> None:
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        max_age=max_age,
        httponly=False,  # the frontend must read this to set the X-CSRF-Token header
        secure=settings.auth_cookie_secure,
        samesite=_samesite(settings),
        domain=settings.auth_cookie_domain,
        path="/",
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, domain=settings.auth_cookie_domain
    )
    response.delete_cookie(CSRF_COOKIE, path="/", domain=settings.auth_cookie_domain)
    response.delete_cookie(ACCESS_COOKIE, path="/api/v1", domain=settings.auth_cookie_domain)
