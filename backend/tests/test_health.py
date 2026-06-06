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
async def test_readyz_returns_status_and_db(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["status"] in ("ready", "not_ready")
    assert body["db"] in ("ok", "down")


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


@pytest.mark.asyncio
async def test_alerts_route_registered(client: AsyncClient) -> None:
    response = await client.get("/api/v1/alerts")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_response_pending_route_registered(client: AsyncClient) -> None:
    response = await client.get("/api/v1/response/pending")
    assert response.status_code == 200
    assert response.json() == []
