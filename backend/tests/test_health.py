"""Smoke tests for health, readiness, error envelope, and request-id propagation."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_always_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_root_index_points_at_docs(client: AsyncClient) -> None:
    # Hitting the API host directly returns a friendly index, not a bare 404.
    response = await client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "SentinelAI API"
    assert body["docs"] == "/docs"
    assert body["health"] == "/health"


@pytest.mark.asyncio
async def test_readyz_reports_structured_dependency_checks(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["status"] in ("ready", "not_ready")
    checks = body["checks"]
    assert checks["database"]["status"] in ("ok", "down")
    assert checks["database"]["required"] is True
    # Redis, task queue, and model are always reported (informational / not required).
    assert "redis" in checks
    assert "queue" in checks
    assert checks["model"]["status"] in ("loaded", "unavailable")
    assert checks["model"]["required"] is False


@pytest.mark.asyncio
async def test_request_id_round_trip(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "test-request-123"})
    assert response.headers.get("x-request-id") == "test-request-123"


@pytest.mark.asyncio
async def test_request_id_generated_when_absent(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers.get("x-request-id")
    assert len(response.headers["x-request-id"]) >= 16


@pytest.mark.asyncio
async def test_404_returns_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/this-does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "http_404"
    assert "request_id" in body


# These two double as route-registration checks: a 401 (not a 404) proves the
# route exists and is wired behind auth. The authenticated "happy path" for
# reads is covered by test_auth.py (GET /auth/me) and the e2e smoke test.
@pytest.mark.asyncio
async def test_alerts_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/alerts")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_response_pending_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/response/pending")
    assert response.status_code == 401
