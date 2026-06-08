"""WebSocket connection manager.

Tracks this process's connected dashboard clients and fans a message out to them
as JSON. Broken sockets are detected on send and dropped, so a client that
vanished without a clean close can't wedge the broadcast loop.

The manager is driven by the **broadcaster** (:mod:`app.core.broadcast`), not the
event bus directly: with Redis pub/sub every worker's broadcaster forwards events
to its own local clients, so fan-out works across workers. In single-process /
dev mode the local broadcaster calls :meth:`broadcast` directly.
"""

from __future__ import annotations

from fastapi import WebSocket

from app.core.events import Event
from app.core.logging import get_logger
from app.core.metrics import WS_CONNECTIONS

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
        WS_CONNECTIONS.set(len(self._clients))
        logger.info("ws.connected", clients=len(self._clients))

    async def remove(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)
        WS_CONNECTIONS.set(len(self._clients))
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
        """Serialize an event and broadcast it to local clients.

        Kept as a convenience (and used by the local broadcaster path / tests);
        the broadcaster is the normal driver of fan-out.
        """
        await self.broadcast(
            {
                "type": event.type,
                "payload": event.payload,
                "ts": event.created_at.isoformat(),
            }
        )


# Process-wide singleton. Fan-out is driven by the broadcaster (see
# app.core.broadcast), which works across workers when Redis is configured.
manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    return manager
