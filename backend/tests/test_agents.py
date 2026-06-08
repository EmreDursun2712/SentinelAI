"""Agent runtime registration tests (unit; DB-free).

Idempotency / no-duplicate-processing against a real DB lives in
``tests/integration/test_agents.py``.
"""

from __future__ import annotations

from app.agents.runtime import AGENT_CLASSES, register_agents
from app.core.events import EventBus, EventType

EXPECTED_NAMES = {
    "agent.detection",
    "agent.triage",
    "agent.response",
    "agent.investigation",
    "agent.reporting",
}

WORKFLOW_EVENTS = [
    EventType.INGESTION_JOB_COMPLETED,
    EventType.ALERT_CREATED,
    EventType.ALERT_TRIAGED,
    EventType.ALERT_RESPONDED,
    EventType.ALERT_INVESTIGATED,
]


def test_register_agents_instantiates_all() -> None:
    agents = register_agents(EventBus())
    assert len(agents) == len(AGENT_CLASSES)
    assert {a.name for a in agents} == EXPECTED_NAMES


def test_register_agents_subscribes_each_workflow_event() -> None:
    # Use an isolated bus so we don't pollute the process-wide bus other tests use.
    bus = EventBus()
    register_agents(bus)
    for event_type in WORKFLOW_EVENTS:
        assert bus.subscriptions(event_type), f"no handler registered for {event_type}"
