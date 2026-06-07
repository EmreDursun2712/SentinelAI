"""WebSocket broadcasting tests.

Covers the event bus (wildcard + failure isolation), the connection manager
(broadcast + pruning of dead sockets), the end-to-end bus → manager path, and
WebSocket authentication via the /stream handshake.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from app.core.events import Event, EventBus, EventType, publish_event
from app.core.security import create_access_token
from app.core.ws_manager import ConnectionManager, get_connection_manager
from app.models.enums import Role

# ---------------------------------------------------------------------------
# Fakes.
# ---------------------------------------------------------------------------


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


class _BrokenWS:
    async def send_json(self, message: dict) -> None:
        raise RuntimeError("socket is dead")


# ---------------------------------------------------------------------------
# Event bus.
# ---------------------------------------------------------------------------


async def test_bus_wildcard_receives_every_event() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def handler(event: Event) -> None:
        seen.append(event.type)

    bus.subscribe("*", handler)
    await bus.publish(Event(type="alert.created"))
    await bus.publish(Event(type="report.created"))
    assert seen == ["alert.created", "report.created"]


async def test_bus_specific_subscription_is_filtered() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def handler(event: Event) -> None:
        seen.append(event.type)

    bus.subscribe("alert.created", handler)
    await bus.publish(Event(type="alert.created"))
    await bus.publish(Event(type="report.created"))  # not subscribed
    assert seen == ["alert.created"]


async def test_bus_isolates_handler_failures() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def bad(event: Event) -> None:
        raise RuntimeError("boom")

    async def good(event: Event) -> None:
        seen.append(event.type)

    bus.subscribe("*", bad)
    bus.subscribe("*", good)
    # Must not raise even though one handler blows up.
    await bus.publish(Event(type="alert.created"))
    assert seen == ["alert.created"]


# ---------------------------------------------------------------------------
# Connection manager.
# ---------------------------------------------------------------------------


async def test_manager_broadcasts_to_all_clients() -> None:
    mgr = ConnectionManager()
    a, b = _FakeWS(), _FakeWS()
    await mgr.add(a)
    await mgr.add(b)
    await mgr.broadcast({"type": "x", "payload": {"n": 1}})
    assert a.sent == [{"type": "x", "payload": {"n": 1}}]
    assert b.sent == [{"type": "x", "payload": {"n": 1}}]


async def test_manager_prunes_dead_sockets() -> None:
    mgr = ConnectionManager()
    good, dead = _FakeWS(), _BrokenWS()
    await mgr.add(good)
    await mgr.add(dead)
    assert mgr.count == 2
    await mgr.broadcast({"type": "x", "payload": {}})
    assert mgr.count == 1  # the broken socket was dropped
    assert good.sent


async def test_manager_on_event_serializes_payload() -> None:
    mgr = ConnectionManager()
    ws = _FakeWS()
    await mgr.add(ws)
    await mgr.on_event(Event(type=EventType.ALERT_CREATED, payload={"alert_id": 7}))
    msg = ws.sent[-1]
    assert msg["type"] == "alert.created"
    assert msg["payload"] == {"alert_id": 7}
    assert "ts" in msg


async def test_publish_event_reaches_connected_client() -> None:
    # End-to-end via the process-wide bus + manager (wired at import).
    mgr = get_connection_manager()
    ws = _FakeWS()
    await mgr.add(ws)
    try:
        await publish_event(EventType.RESPONSE_ACTION_EXECUTED, {"action_id": 3})
        assert any(m["type"] == "response.action_executed" for m in ws.sent)
    finally:
        await mgr.remove(ws)


# ---------------------------------------------------------------------------
# WebSocket authentication (handshake).
# ---------------------------------------------------------------------------


def test_ws_rejects_missing_token(app: FastAPI) -> None:
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/v1/stream") as ws:
        ws.receive_text()


def test_ws_rejects_invalid_token(app: FastAPI) -> None:
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/v1/stream?token=not-a-jwt") as ws,
    ):
        ws.receive_text()


def test_ws_accepts_valid_token(app: FastAPI) -> None:
    token, _ = create_access_token("alice", {"role": Role.VIEWER.value})
    client = TestClient(app)
    with client.websocket_connect(f"/api/v1/stream?token={token}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "stream.connected"
        assert hello["payload"]["user"] == "alice"
