"""Batch flow ingestion + sensor status endpoint tests.

Auth + serialization are covered with the service layer stubbed and the DB
session overridden, so the suite stays DB-free.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import db_session
from app.api.routers import ingest as ingest_router
from app.core.security import create_access_token
from app.models.enums import Role


async def _dummy_session() -> AsyncIterator[None]:
    yield None


def _headers(role: Role) -> dict[str, str]:
    token, _ = create_access_token("sensor-svc", {"role": role.value})
    return {"Authorization": f"Bearer {token}"}


def _flow() -> dict:
    return {
        "event_time": "2026-01-01T00:00:00Z",
        "src_ip": "192.168.1.10",
        "dst_ip": "192.168.1.20",
        "src_port": 44321,
        "dst_port": 443,
        "protocol": "tcp",
        "features": {"flow_duration": 1.5, "total_fwd_packets": 12},
    }


# ---------------------------------------------------------------------------
# Auth.
# ---------------------------------------------------------------------------


async def test_batch_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/ingest/flows", json={"flows": [_flow()]})
    assert resp.status_code == 401


async def test_batch_forbidden_for_viewer(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/ingest/flows", json={"flows": [_flow()]}, headers=_headers(Role.VIEWER)
    )
    assert resp.status_code == 403


async def test_sensor_status_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/ingest/sensor/status")).status_code == 401


# ---------------------------------------------------------------------------
# Happy paths (service stubbed).
# ---------------------------------------------------------------------------


async def test_batch_ingest_inserts_flows(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[db_session] = _dummy_session

    async def fake_insert(session, flows, **kw):
        assert len(flows) == 2
        return len(flows)

    monkeypatch.setattr(ingest_router, "insert_flow_batch", fake_insert)

    resp = await client.post(
        "/api/v1/ingest/flows",
        json={"flows": [_flow(), _flow()]},
        headers=_headers(Role.ANALYST),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body == {
        "received": 2,
        "inserted": 2,
        "detection_ran": False,
        "alerts_created": 0,
    }
    app.dependency_overrides.clear()


async def test_batch_rejects_invalid_flow(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[db_session] = _dummy_session
    bad = _flow() | {"src_ip": "not-an-ip"}
    resp = await client.post(
        "/api/v1/ingest/flows", json={"flows": [bad]}, headers=_headers(Role.ANALYST)
    )
    assert resp.status_code == 400  # clean validation error before any insert
    assert resp.json()["error"]["code"] == "bad_request"
    app.dependency_overrides.clear()


async def test_sensor_status_serializes(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[db_session] = _dummy_session
    now = datetime.now(UTC)

    async def fake_status(session, *, live_window_seconds):
        return {
            "live": True,
            "last_event_at": now,
            "events_recent": 7,
            "total_events": 123,
            "live_window_seconds": live_window_seconds,
        }

    monkeypatch.setattr(ingest_router, "sensor_status", fake_status)
    resp = await client.get("/api/v1/ingest/sensor/status", headers=_headers(Role.VIEWER))
    assert resp.status_code == 200
    body = resp.json()
    assert body["live"] is True
    assert body["events_recent"] == 7
    assert body["total_events"] == 123
    app.dependency_overrides.clear()
