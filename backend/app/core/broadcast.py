"""WebSocket fan-out broadcaster — Redis pub/sub across workers, local fallback.

The problem: WebSocket clients connect to *one* backend worker, but events are
published on whichever worker handled the triggering request. To reach every
client, the fan-out must cross process boundaries.

* :class:`RedisBroadcaster` — ``broadcast`` ``PUBLISH``es the event to a Redis
  channel; a per-process subscriber loop receives every message (including its
  own) and forwards it to that process's local WebSocket clients. So N workers
  all deliver to their own clients regardless of where the event originated.
* :class:`LocalBroadcaster` — dev / single-worker fallback: ``broadcast`` calls
  the local connection manager directly. No cross-worker delivery.

Production uses Redis (already required there for rate limiting). The active
broadcaster is chosen at startup; tests + ``--reload`` get the lazy local default.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Protocol

from app.core.events import Event
from app.core.logging import get_logger
from app.core.ws_manager import get_connection_manager

logger = get_logger(__name__)

CHANNEL = "sentinelai:events"


def _to_message(event: Event) -> dict:
    return {"type": event.type, "payload": event.payload, "ts": event.created_at.isoformat()}


class Broadcaster(Protocol):
    backend: str

    async def broadcast(self, event: Event) -> None: ...

    async def start(self) -> None: ...

    async def aclose(self) -> None: ...


class LocalBroadcaster:
    """Single-process fan-out: straight to this process's WS clients."""

    backend = "local"

    async def broadcast(self, event: Event) -> None:
        await get_connection_manager().broadcast(_to_message(event))

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class RedisBroadcaster:
    """Cross-worker fan-out via Redis pub/sub.

    ``broadcast`` only publishes; delivery to local clients happens in the
    subscriber loop (started by :meth:`start`), so every worker — including the
    publisher — delivers via the same path.
    """

    backend = "redis"

    def __init__(self, client, channel: str = CHANNEL) -> None:
        self._client = client
        self._channel = channel
        self._task: asyncio.Task | None = None

    async def broadcast(self, event: Event) -> None:
        await self._client.publish(self._channel, json.dumps(_to_message(event)))

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._subscribe_loop())
        logger.info("broadcast.redis_started", channel=self._channel)

    async def _subscribe_loop(self) -> None:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._channel)
        manager = get_connection_manager()
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                except (ValueError, TypeError, KeyError):
                    continue
                await manager.broadcast(data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep the worker alive if the loop dies
            logger.warning("broadcast.redis_loop_error", error=str(exc))
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(self._channel)
                await pubsub.aclose()

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


_broadcaster: Broadcaster | None = None


def get_broadcaster() -> Broadcaster:
    """Active broadcaster, lazily defaulting to local (tests / reload workers)."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = LocalBroadcaster()
    return _broadcaster


def set_broadcaster(broadcaster: Broadcaster) -> None:
    global _broadcaster
    _broadcaster = broadcaster
