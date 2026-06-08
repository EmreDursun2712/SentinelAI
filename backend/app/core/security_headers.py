"""Defense-in-depth HTTP security headers + CORS origin validation.

``SecurityHeadersMiddleware`` stamps every response with a practical baseline:
CSP, ``X-Content-Type-Options``, ``X-Frame-Options``, ``Referrer-Policy``,
``Permissions-Policy``, and (when enabled) HSTS. The interactive API docs get a
looser CSP so Swagger UI's CDN assets + inline init still load.

``validate_cors_origins`` rejects unsafe CORS config (notably ``*`` with
credentials) — fatal in production, a warning in dev.
"""

from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Tight default for the JSON API: nothing loads by default; the app's own UI is
# served (and CSP-managed) by the frontend host. See docs/DEPLOYMENT_SECURITY.md.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"

# Swagger UI / ReDoc pull assets from jsDelivr and use inline init script/styles.
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none'; base-uri 'none'"
)

_PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
    "microphone=(), payment=(), usb=()"
)

# 1 year; includeSubDomains. (No `preload` — that requires list registration.)
_HSTS_VALUE = "max-age=31536000; includeSubDomains"

_DOCS_PREFIXES = ("/docs", "/redoc")


def _csp_for(path: str) -> str:
    return _DOCS_CSP if path.startswith(_DOCS_PREFIXES) else _API_CSP


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts: bool) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("Content-Security-Policy", _csp_for(request.url.path))
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Permissions-Policy", _PERMISSIONS_POLICY)
        if self._hsts:
            # Only meaningful behind TLS; harmless (ignored) over plain HTTP.
            headers.setdefault("Strict-Transport-Security", _HSTS_VALUE)
        return response


def validate_cors_origins(origins: list[str], *, allow_credentials: bool) -> list[str]:
    """Return a list of problems with the configured CORS origins (empty ⇒ ok).

    Disallows the ``*`` wildcard when credentials are enabled (the browser would
    reject it and it is unsafe), and requires each origin to be a bare
    ``scheme://host[:port]`` with no path or embedded wildcard.
    """
    issues: list[str] = []
    for origin in origins:
        if origin == "*":
            if allow_credentials:
                issues.append("wildcard '*' origin is not allowed with credentials")
            continue
        if "*" in origin:
            issues.append(f"wildcard in origin '{origin}' is not supported")
            continue
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            issues.append(f"invalid origin '{origin}' (expected scheme://host[:port])")
        elif parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            issues.append(f"origin '{origin}' must not include a path/query/fragment")
    return issues
