"""In-process pub/sub event bus shared across agents and the WebSocket layer.

Handlers may subscribe to a specific event type or to the wildcard ``"*"`` to
receive every event (the WebSocket connection manager uses the wildcard).
``publish`` isolates handler failures so one broken subscriber (e.g. a dead
socket) can never break the publishing path or the request that triggered it.

NOTE: this bus is in-process. With a single uvicorn worker it is sufficient;
horizontal scaling would need a shared broker (e.g. Redis pub/sub).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

EventHandler = Callable[["Event"], Awaitable[None]]

WILDCARD = "*"


class EventType:
    """Canonical event names broadcast to clients. Payloads stay small and safe
    (ids, status, severity, counts, timestamps) — never full JSON artifacts."""

    ALERT_CREATED = "alert.created"
    ALERT_TRIAGED = "alert.triaged"
    ALERT_RESPONDED = "alert.responded"
    ALERT_INVESTIGATED = "alert.investigated"
    ALERT_REPORTED = "alert.reported"
    ALERT_CLOSED = "alert.closed"
    ALERT_DISPOSITION_UPDATED = "alert.disposition_updated"
    RESPONSE_ACTION_PENDING = "response.action_pending"
    RESPONSE_ACTION_EXECUTED = "response.action_executed"
    RESPONSE_ACTION_REJECTED = "response.action_rejected"
    INGESTION_JOB_COMPLETED = "ingestion.job_completed"
    DETECTION_RUN_COMPLETED = "detection.run_completed"
    REPORT_CREATED = "report.created"


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        handlers = [
            *self._handlers.get(event.type, ()),
            *self._handlers.get(WILDCARD, ()),
        ]
        if not handlers:
            return
        results = await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning("event.handler_failed", type=event.type, error=str(result))


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus


async def publish_event(event_type: str, payload: dict[str, Any] | None = None) -> None:
    """Convenience: build and publish an :class:`Event`.

    Never raises — call this **after** a successful DB commit so rolled-back
    changes are never broadcast, and so a broadcasting hiccup can't fail the
    request whose data is already committed.
    """
    await _bus.publish(Event(type=event_type, payload=payload or {}))
