"""Investigation agent — thin wrapper around the investigation service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
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
        # Triggered explicitly from the API; event-bus subscription lands
        # alongside the agent runtime.
        return None

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

    async def latest_packet(
        self, session: AsyncSession, alert_id: int
    ) -> AlertArtifact | None:
        return await get_latest_investigation(session, alert_id)
