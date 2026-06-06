"""WebSocket connection manager.

Tracks the set of connected dashboard clients and fans out every event bus
message to them as JSON. Broken sockets are detected on send and dropped, so a
client that vanished without a clean close can't wedge the broadcast loop.

The manager subscribes to the event bus wildcard at import time, so any
``publish_event(...)`` anywhere in the app reaches connected clients without
extra wiring.
"""

from __future__ import annotations

from fastapi import WebSocket

from app.core.events import Event, get_event_bus
from app.core.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Tracks connected clients and fans events out to them.

    asyncio is single-threaded, so mutating the client set between ``await``
    points is the only hazard. ``broadcast`` works on a synchronous snapshot and
    ``set.add``/``set.discard`` are atomic, so no explicit lock is needed — which
    also avoids binding a lock to a particular event loop (important for tests).
    """

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def add(self, websocket: WebSocket) -> None:
        self._clients.add(websocket)
        logger.info("ws.connected", clients=len(self._clients))

    async def remove(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)
        logger.info("ws.disconnected", clients=len(self._clients))

    @property
    def count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict) -> None:
        targets = list(self._clients)  # synchronous snapshot
        if not targets:
            return
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)
        if dead:
            logger.info("ws.pruned", removed=len(dead), clients=len(self._clients))

    async def on_event(self, event: Event) -> None:
        """Bus handler: serialize an event and broadcast it."""
        await self.broadcast(
            {
                "type": event.type,
                "payload": event.payload,
                "ts": event.created_at.isoformat(),
            }
        )


# Process-wide singleton, wired to the event bus once at import.
manager = ConnectionManager()
get_event_bus().subscribe("*", manager.on_event)


def get_connection_manager() -> ConnectionManager:
    return manager
