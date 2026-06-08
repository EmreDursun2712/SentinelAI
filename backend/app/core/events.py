"""Event dispatcher: in-process handlers + cross-worker WebSocket fan-out.

Two distinct concerns, intentionally separated:

* **In-process bus** (:class:`EventBus`) — drives *business* handlers (the agent
  runtime) and runs only on the worker that published the event. Agents subscribe
  here; handlers must be idempotent (see ``app.agents``).
* **Broadcaster** (:mod:`app.core.broadcast`) — drives *WebSocket* fan-out. With
  Redis it publishes to a channel every worker subscribes to, so a client
  connected to any worker receives events published by any other worker. Without
  Redis it falls back to a local in-process broadcast (dev / single worker).

``publish_event`` does both: dispatch to local handlers, then hand the event to
the broadcaster. Call it **after** a successful DB commit (post-commit emit) so
rolled-back work is never dispatched or broadcast.

Payload contract: payloads stay small and non-sensitive (ids, status, severity,
counts, timestamps) — never tokens, passwords, or full artifacts. See
``EVENT_PAYLOAD_KEYS`` for the expected keys per event type.
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
    """Canonical event names. Workflow events (``alert.*``, ``ingestion.*``,
    ``detection.*``) drive the agent runtime; all are broadcast to WS clients."""

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
    TASK_UPDATED = "task.updated"


# Lightweight payload "schema": the expected (non-sensitive) keys per event.
# Documents the contract for consumers (agents, the dashboard) without imposing
# heavyweight validation on the hot path.
EVENT_PAYLOAD_KEYS: dict[str, list[str]] = {
    EventType.ALERT_CREATED: ["alert_id", "src_ip", "dst_ip", "prediction", "confidence"],
    EventType.ALERT_TRIAGED: ["alert_id", "severity", "priority"],
    EventType.ALERT_RESPONDED: ["alert_id", "status"],
    EventType.ALERT_INVESTIGATED: ["alert_id"],
    EventType.ALERT_REPORTED: ["alert_id"],
    EventType.ALERT_CLOSED: ["alert_id"],
    EventType.ALERT_DISPOSITION_UPDATED: ["alert_id", "disposition"],
    EventType.RESPONSE_ACTION_PENDING: ["alert_id", "count"],
    EventType.RESPONSE_ACTION_EXECUTED: ["alert_id", "action_id", "action_type"],
    EventType.RESPONSE_ACTION_REJECTED: ["alert_id", "action_id", "action_type"],
    EventType.INGESTION_JOB_COMPLETED: ["job_id", "kind", "total_rows", "valid_rows"],
    EventType.DETECTION_RUN_COMPLETED: ["processed", "alerts_created"],
    EventType.REPORT_CREATED: ["report_id", "kind"],
    EventType.TASK_UPDATED: ["task_id", "kind", "status", "progress"],
}


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventBus:
    """In-process dispatcher. Handlers subscribe by exact type or ``"*"``.

    ``publish`` isolates handler failures so one broken handler can never break
    the publishing path or the request that triggered it.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def subscriptions(self, event_type: str) -> list[EventHandler]:
        """Handlers registered for ``event_type`` (incl. wildcard). For tests."""
        return [*self._handlers.get(event_type, ()), *self._handlers.get(WILDCARD, ())]

    def clear(self) -> None:
        self._handlers.clear()

    async def publish(self, event: Event) -> None:
        handlers = self.subscriptions(event.type)
        if not handlers:
            return
        results = await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning("event.handler_failed", type=event.type, error=str(result))


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus


async def publish_event(event_type: str, payload: dict[str, Any] | None = None) -> Event:
    """Dispatch to in-process handlers, then broadcast to WS clients.

    Never raises — call this **after** a successful DB commit. Returns the
    :class:`Event` (handy for tests / chaining).
    """
    event = Event(type=event_type, payload=payload or {})
    # 1) Business handlers (agents) — this worker only.
    await _bus.publish(event)
    # 2) WebSocket fan-out — across workers via Redis (or local fallback).
    #    Imported lazily to avoid an import cycle (broadcast → ws_manager).
    from app.core.broadcast import get_broadcaster

    try:
        await get_broadcaster().broadcast(event)
    except Exception as exc:  # broadcasting must never fail the caller
        logger.warning("event.broadcast_failed", type=event_type, error=str(exc))
    return event
