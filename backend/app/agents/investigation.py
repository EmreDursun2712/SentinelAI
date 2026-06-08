"""Investigation agent.

Analyst-triggered by default. When ``SENTINEL_INVESTIGATION_AUTO`` is enabled it
subscribes to ``alert.responded`` and builds an investigation packet
automatically — idempotent: it skips alerts that already have a packet.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.events import Event, EventType
from app.models import Alert, AlertArtifact
from app.schemas.investigation import InvestigationPacket
from app.services.investigation_service import (
    DEFAULT_ALERTS_WINDOW_HOURS,
    DEFAULT_EVENTS_WINDOW_MINUTES,
    DEFAULT_MAX_ALERTS,
    DEFAULT_MAX_EVENTS,
    get_latest_investigation,
    investigate_alert,
)


class InvestigationAgent(Agent):
    name = "agent.investigation"

    def register(self) -> None:
        # Subscribe unconditionally; the handler checks the auto flag at runtime
        # so config can flip without re-registration. Default: analyst-triggered.
        self.bus.subscribe(EventType.ALERT_RESPONDED, self.on_alert_responded)

    async def on_alert_responded(self, event: Event) -> None:
        if not get_settings().investigation_auto:
            return
        alert_id = event.payload.get("alert_id")
        if alert_id is None:
            return
        async with session_scope() as session:
            await self.investigate_if_needed(session, int(alert_id))

    async def investigate_if_needed(
        self, session: AsyncSession, alert_id: int
    ) -> AlertArtifact | None:
        """Build a packet iff none exists yet. Idempotent (emits alert.investigated)."""
        alert = await session.get(Alert, alert_id)
        if alert is None:
            return None
        if await get_latest_investigation(session, alert_id) is not None:
            return None
        artifact, _ = await self.investigate(session, alert, commit=True)
        self.logger.info("agent.investigation.auto_ran", alert_id=alert_id)
        return artifact

    async def investigate(
        self,
        session: AsyncSession,
        alert: Alert,
        *,
        events_window_minutes: int = DEFAULT_EVENTS_WINDOW_MINUTES,
        alerts_window_hours: int = DEFAULT_ALERTS_WINDOW_HOURS,
        max_events: int = DEFAULT_MAX_EVENTS,
        max_alerts: int = DEFAULT_MAX_ALERTS,
        commit: bool = True,
    ) -> tuple[AlertArtifact, InvestigationPacket]:
        return await investigate_alert(
            session,
            alert,
            events_window_minutes=events_window_minutes,
            alerts_window_hours=alerts_window_hours,
            max_events=max_events,
            max_alerts=max_alerts,
            commit=commit,
        )

    async def latest_packet(self, session: AsyncSession, alert_id: int) -> AlertArtifact | None:
        return await get_latest_investigation(session, alert_id)
