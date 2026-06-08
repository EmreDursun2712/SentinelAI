"""Double-submit CSRF protection for cookie-authenticated mutations.

Only requests that actually carry an auth cookie are subject to the check —
Bearer-token (header) requests can't be forged cross-site, so they're exempt and
unchanged. For an unsafe method (POST/PUT/PATCH/DELETE) on a cookie-authed
request, the ``X-CSRF-Token`` header must match the readable ``sentinelai_csrf``
cookie (constant-time compare).

SameSite already blocks most cross-site cookie sends; this double-submit token is
defense-in-depth and the primary protection when cookies are configured
``SameSite=None`` (a cross-site frontend deployment).
"""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.cookies import AUTH_COOKIE_NAMES, CSRF_COOKIE, CSRF_HEADER

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Bootstrap / teardown endpoints are exempt: login has no cookie yet, and logout
# must always succeed so a user can't be locked into a session. (SameSite still
# guards these against cross-site cookie sends.)
EXEMPT_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/logout-all",
    }
)


def _is_cookie_authenticated(request: Request) -> bool:
    return any(name in request.cookies for name in AUTH_COOKIE_NAMES)


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if (
            request.method not in SAFE_METHODS
            and request.url.path not in EXEMPT_PATHS
            and _is_cookie_authenticated(request)
        ):
            cookie = request.cookies.get(CSRF_COOKIE)
            header = request.headers.get(CSRF_HEADER)
            if not cookie or not header or not secrets.compare_digest(cookie, header):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "csrf_failed",
                            "message": (
                                "Missing or invalid CSRF token for a cookie-authenticated "
                                "request. Send the sentinelai_csrf cookie value in the "
                                "X-CSRF-Token header."
                            ),
                            "details": None,
                        },
                        "request_id": getattr(request.state, "request_id", None),
                    },
                )
        return await call_next(request)
