"""Detection agent — runs detection on freshly ingested flows.

Subscribes to ``ingestion.job_completed``; when
``SENTINEL_DETECTION_AUTO_RUN_ON_INGEST`` is set it classifies the undetected
events for **REPLAY** (CSV) jobs. The sensor's STREAM ``/ingest/flows`` endpoint
auto-detects inline (and reports it in its response), so the agent skips STREAM
jobs to avoid double processing. ``fetch_undetected_events`` makes the run
idempotent — already-classified events are never reprocessed.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import AppError
from app.core.events import Event, EventType
from app.models.enums import IngestionKind
from app.services.detection_service import (
    Prediction,
    detect_events,
    fetch_undetected_events,
)
from app.services.model_registry import get_model_registry


class DetectionAgent(Agent):
    name = "agent.detection"

    def register(self) -> None:
        self.bus.subscribe(EventType.INGESTION_JOB_COMPLETED, self.on_ingestion_completed)

    async def on_ingestion_completed(self, event: Event) -> None:
        settings = get_settings()
        if not settings.detection_auto_run_on_ingest:
            return
        # STREAM (sensor) ingestion auto-detects inline in its own endpoint.
        if event.payload.get("kind") != IngestionKind.REPLAY.value:
            return
        if not get_model_registry().is_loaded():
            self.logger.warning("agent.detection.no_model")
            return
        async with session_scope() as session:
            preds = await self.process_recent(session, limit=settings.detection_auto_run_limit)
        self.logger.info("agent.detection.auto_ran", processed=len(preds))

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
