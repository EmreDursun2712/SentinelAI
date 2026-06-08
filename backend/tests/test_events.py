"""Event dispatcher tests: payload schema coverage + publish_event fan-out."""

from __future__ import annotations

import pytest

from app.core import broadcast as broadcast_mod
from app.core.events import (
    EVENT_PAYLOAD_KEYS,
    Event,
    EventBus,
    EventType,
    get_event_bus,
    publish_event,
)


def test_payload_keys_cover_every_event_type() -> None:
    declared = {
        v for k, v in vars(EventType).items() if isinstance(v, str) and not k.startswith("_")
    }
    assert declared == set(EVENT_PAYLOAD_KEYS)


async def test_bus_subscriptions_helper() -> None:
    bus = EventBus()

    async def h(_: Event) -> None: ...

    bus.subscribe(EventType.ALERT_CREATED, h)
    bus.subscribe("*", h)
    assert len(bus.subscriptions(EventType.ALERT_CREATED)) == 2  # specific + wildcard
    assert len(bus.subscriptions(EventType.ALERT_TRIAGED)) == 1  # wildcard only


async def test_publish_event_hits_bus_and_broadcaster() -> None:
    seen_bus: list[str] = []
    seen_broadcast: list[str] = []

    class _FakeBroadcaster:
        backend = "fake"

        async def broadcast(self, event: Event) -> None:
            seen_broadcast.append(event.type)

        async def start(self) -> None: ...

        async def aclose(self) -> None: ...

    bus = get_event_bus()

    async def handler(event: Event) -> None:
        seen_bus.append(event.type)

    bus.subscribe(EventType.ALERT_CREATED, handler)
    previous = broadcast_mod.get_broadcaster()
    broadcast_mod.set_broadcaster(_FakeBroadcaster())
    try:
        event = await publish_event(EventType.ALERT_CREATED, {"alert_id": 1})
    finally:
        bus.clear()
        broadcast_mod.set_broadcaster(previous)

    assert event.type == "alert.created"
    assert seen_bus == ["alert.created"]  # in-process handler ran
    assert seen_broadcast == ["alert.created"]  # broadcaster ran


async def test_publish_event_never_raises_on_broadcaster_error() -> None:
    class _BoomBroadcaster:
        backend = "boom"

        async def broadcast(self, event: Event) -> None:
            raise RuntimeError("redis down")

        async def start(self) -> None: ...

        async def aclose(self) -> None: ...

    previous = broadcast_mod.get_broadcaster()
    broadcast_mod.set_broadcaster(_BoomBroadcaster())
    try:
        # Must not raise even though the broadcaster blows up.
        await publish_event(EventType.REPORT_CREATED, {"report_id": 1, "kind": "PER_ALERT"})
    finally:
        broadcast_mod.set_broadcaster(previous)


@pytest.mark.parametrize("missing_id", [None])
async def test_publish_event_returns_event(missing_id) -> None:
    event = await publish_event(EventType.ALERT_CLOSED, {"alert_id": 9})
    assert event.payload == {"alert_id": 9}
