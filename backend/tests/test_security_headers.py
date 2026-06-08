"""Security-headers middleware + CORS-origin validation tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security_headers import (
    SecurityHeadersMiddleware,
    validate_cors_origins,
)
from app.main import create_app

# ---------------------------------------------------------------------------
# Security headers present on responses.
# ---------------------------------------------------------------------------


async def test_security_headers_present_on_public_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "permissions-policy" in resp.headers
    csp = resp.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


async def test_security_headers_present_on_401(client: AsyncClient) -> None:
    # Even an unauthenticated rejection carries the headers (middleware is outermost).
    resp = await client.get("/api/v1/alerts")
    assert resp.status_code == 401
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in resp.headers


async def test_docs_get_a_relaxed_csp(client: AsyncClient) -> None:
    resp = await client.get("/docs")
    assert resp.status_code == 200
    csp = resp.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" in csp  # Swagger UI assets allowed
    assert "default-src 'self'" in csp


async def test_no_hsts_by_default_but_present_when_enabled() -> None:
    # Default (dev): no HSTS.
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        resp = await ac.get("/health")
    assert "strict-transport-security" not in resp.headers

    # Forced on: HSTS present. Apply the middleware directly with hsts=True.
    app2 = create_app()
    app2.add_middleware(SecurityHeadersMiddleware, hsts=True)
    transport2 = ASGITransport(app=app2)
    async with AsyncClient(transport=transport2, base_url="https://test") as ac:
        resp2 = await ac.get("/health")
    assert resp2.headers["strict-transport-security"].startswith("max-age=")


# ---------------------------------------------------------------------------
# CORS origin validation.
# ---------------------------------------------------------------------------


def test_cors_wildcard_with_credentials_is_rejected() -> None:
    issues = validate_cors_origins(["*"], allow_credentials=True)
    assert issues and "wildcard" in issues[0]


def test_cors_valid_origins_pass() -> None:
    assert (
        validate_cors_origins(
            ["http://localhost:5173", "https://app.example.com"], allow_credentials=True
        )
        == []
    )


def test_cors_rejects_paths_and_embedded_wildcards() -> None:
    issues = validate_cors_origins(
        ["https://app.example.com/app", "https://*.example.com", "not-a-url"],
        allow_credentials=True,
    )
    assert len(issues) == 3


@pytest.mark.parametrize("origin", ["ftp://x", "://nohost", "javascript:alert(1)"])
def test_cors_rejects_bad_schemes(origin: str) -> None:
    assert validate_cors_origins([origin], allow_credentials=True)
