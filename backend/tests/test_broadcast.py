"""WebSocket broadcaster tests: local fan-out + Redis pub/sub (fake) + prod guard."""

from __future__ import annotations

import asyncio

import pytest

from app.core.broadcast import LocalBroadcaster, RedisBroadcaster
from app.core.config import Settings
from app.core.events import Event, EventType
from app.core.ws_manager import get_connection_manager
from app.main import _configure_broadcaster, _configure_rate_limiter


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


async def test_local_broadcaster_delivers_to_local_manager() -> None:
    mgr = get_connection_manager()
    ws = _FakeWS()
    await mgr.add(ws)
    try:
        await LocalBroadcaster().broadcast(
            Event(type=EventType.ALERT_CREATED, payload={"alert_id": 5})
        )
        assert any(m["type"] == "alert.created" and m["payload"]["alert_id"] == 5 for m in ws.sent)
    finally:
        await mgr.remove(ws)


# --- Fake Redis pub/sub: publish() fans data to each subscriber queue --------


class _FakePubSub:
    def __init__(self, hub: _FakeRedis) -> None:
        self._hub = hub
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def subscribe(self, _channel: str) -> None:
        self._hub.subscribers.append(self._queue)

    async def unsubscribe(self, _channel: str) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def listen(self):
        while True:
            data = await self._queue.get()
            yield {"type": "message", "data": data}


class _FakeRedis:
    def __init__(self) -> None:
        self.subscribers: list[asyncio.Queue[str]] = []

    async def publish(self, _channel: str, data: str) -> None:
        for q in self.subscribers:
            await q.put(data)

    def pubsub(self) -> _FakePubSub:
        return _FakePubSub(self)


async def test_redis_broadcaster_fans_out_via_pubsub() -> None:
    """Simulates the cross-worker path: publish → channel → subscriber → local WS."""
    mgr = get_connection_manager()
    ws = _FakeWS()
    await mgr.add(ws)
    broadcaster = RedisBroadcaster(_FakeRedis())
    await broadcaster.start()
    await asyncio.sleep(0.05)  # let the subscriber loop subscribe
    try:
        await broadcaster.broadcast(
            Event(type=EventType.RESPONSE_ACTION_EXECUTED, payload={"action_id": 3})
        )
        for _ in range(20):
            if any(m["type"] == "response.action_executed" for m in ws.sent):
                break
            await asyncio.sleep(0.02)
        assert any(m["type"] == "response.action_executed" for m in ws.sent)
    finally:
        await broadcaster.aclose()
        await mgr.remove(ws)


async def test_broadcaster_requires_redis_in_production() -> None:
    settings = Settings(env="production", redis_url=None)
    with pytest.raises(RuntimeError):
        await _configure_broadcaster(settings)


async def test_rate_limiter_requires_redis_in_production() -> None:
    # No in-memory limiter in production: missing Redis fails closed.
    settings = Settings(env="production", redis_url=None)
    with pytest.raises(RuntimeError):
        await _configure_rate_limiter(settings)
