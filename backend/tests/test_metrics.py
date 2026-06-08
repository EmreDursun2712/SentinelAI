"""Prometheus /metrics exposition tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_metrics_returns_prometheus_exposition(client: AsyncClient) -> None:
    # Generate one HTTP sample first so the request counter has a series.
    await client.get("/health")

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")

    body = resp.text
    # Metric families are present (HELP/TYPE lines exist even at zero).
    assert "sentinelai_http_requests_total" in body
    assert "sentinelai_http_request_duration_seconds" in body
    assert "sentinelai_websocket_active_connections" in body
    assert "sentinelai_detection_runs_total" in body
    assert "sentinelai_response_actions_total" in body
    assert "sentinelai_ingestion_jobs_total" in body


@pytest.mark.asyncio
async def test_http_request_counter_labels_by_route(client: AsyncClient) -> None:
    await client.get("/health")
    body = (await client.get("/metrics")).text
    # The matched route template is used as a label (low cardinality, no IDs).
    assert 'route="/health"' in body
    assert 'method="GET"' in body
