"""Triage agent — triages newly created alerts.

Subscribes to ``alert.created``. The synchronous detection pipeline already
triages alerts it creates (one transaction), so this handler is an **idempotent**
safety net: it triages only alerts still in ``NEW`` status and no-ops for ones
already triaged — repeated/duplicate events never re-triage. ``triage_alert``
emits ``alert.triaged`` on commit, which the Response agent picks up.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.core.db import session_scope
from app.core.events import Event, EventType
from app.models import Alert
from app.models.enums import AlertStatus
from app.services.triage_rules import TriageScore
from app.services.triage_service import triage_alert


class TriageAgent(Agent):
    name = "agent.triage"

    def register(self) -> None:
        self.bus.subscribe(EventType.ALERT_CREATED, self.on_alert_created)

    async def on_alert_created(self, event: Event) -> None:
        alert_id = event.payload.get("alert_id")
        if alert_id is None:
            return
        async with session_scope() as session:
            await self.triage_if_new(session, int(alert_id))

    async def triage_if_new(self, session: AsyncSession, alert_id: int) -> TriageScore | None:
        """Triage the alert iff it's still NEW. Idempotent — no duplicate triage."""
        alert = await session.get(Alert, alert_id)
        if alert is None or alert.status != AlertStatus.NEW:
            return None
        score = await self.score(session, alert, commit=True)
        self.logger.info("agent.triage.scored", alert_id=alert_id)
        return score

    async def score(
        self,
        session: AsyncSession,
        alert: Alert,
        *,
        window_minutes: int = 15,
        commit: bool = True,
    ) -> TriageScore:
        return await triage_alert(session, alert, window_minutes=window_minutes, commit=commit)
