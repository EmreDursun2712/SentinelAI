"""Agent runtime: register the five agents on the in-process event bus.

Called once at startup (``app.main`` lifespan). Each agent subscribes its
handlers; handlers are idempotent + state-guarded so the event-driven workflow
never duplicates the synchronous detection pipeline's work:

    ingestion.job_completed  → DetectionAgent  (REPLAY jobs, if auto-run on)
    alert.created            → TriageAgent      (triage if still NEW)
    alert.triaged           → ResponseAgent     (respond if TRIAGED, no actions)
    alert.responded         → InvestigationAgent (only if investigation_auto)
    alert.investigated      → ReportingAgent     (only if reporting_auto)

Explicit API actions still work directly through the services; the agents are the
automatic, event-driven layer on top.
"""

from __future__ import annotations

from app.agents.base import Agent
from app.agents.detection import DetectionAgent
from app.agents.investigation import InvestigationAgent
from app.agents.reporting import ReportingAgent
from app.agents.response import ResponseAgent
from app.agents.triage import TriageAgent
from app.core.events import EventBus, get_event_bus
from app.core.logging import get_logger

logger = get_logger(__name__)

AGENT_CLASSES: tuple[type[Agent], ...] = (
    DetectionAgent,
    TriageAgent,
    ResponseAgent,
    InvestigationAgent,
    ReportingAgent,
)


def register_agents(bus: EventBus | None = None) -> list[Agent]:
    """Instantiate + register every agent on ``bus`` (default: the global bus)."""
    bus = bus or get_event_bus()
    agents = [cls(bus) for cls in AGENT_CLASSES]
    for agent in agents:
        agent.register()
    logger.info("agents.registered", agents=[a.name for a in agents])
    return agents
