"""Triage agent — thin wrapper around the triage service.

Phase 4 wires this via direct calls from the Detection service (auto-triage
runs inline after each alert is created). Phase 5+ will move the trigger to
the in-process event bus, but the entry point stays the same.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.models import Alert
from app.services.triage_rules import TriageScore
from app.services.triage_service import triage_alert


class TriageAgent(Agent):
    name = "agent.triage"

    def register(self) -> None:
        # The Detection service invokes triage_alert directly; the event-bus
        # subscription lands when the agent runtime is wired up.
        return None

    async def score(
        self,
        session: AsyncSession,
        alert: Alert,
        *,
        window_minutes: int = 15,
        commit: bool = True,
    ) -> TriageScore:
        return await triage_alert(
            session, alert, window_minutes=window_minutes, commit=commit
        )
