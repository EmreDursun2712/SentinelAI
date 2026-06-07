"""Detection agent — thin wrapper around the detection service.

Phase 4 will wire this agent's ``process_recent`` into the ingestion completion
event so detection runs automatically. For now, callers invoke it explicitly
via either ``DetectionAgent.process_recent(session, ...)`` or the HTTP API.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.core.config import get_settings
from app.core.errors import AppError
from app.services.detection_service import (
    Prediction,
    detect_events,
    fetch_undetected_events,
)
from app.services.model_registry import get_model_registry


class DetectionAgent(Agent):
    name = "agent.detection"

    def register(self) -> None:
        # Subscription wiring lands in Phase 4 alongside the agent runtime.
        return None

    async def process_recent(self, session: AsyncSession, limit: int = 100) -> list[Prediction]:
        bundle = get_model_registry().get()
        if bundle is None:
            raise AppError("Detection model is not loaded.")
        settings = get_settings()
        events = await fetch_undetected_events(session, limit)
        return await detect_events(
            session,
            bundle,
            events,
            threshold=settings.detection_threshold,
            benign_label=settings.detection_benign_label,
        )
