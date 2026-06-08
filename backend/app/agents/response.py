"""Response agent — thin wrapper around the response service.

Ethics: actions are ``simulated`` by default. The DB CHECK
``ck_response_actions_simulated_unless_lab`` makes a non-simulated row possible
ONLY in ``execution_mode='LAB'`` — and LAB is itself disabled unless explicitly,
safely configured (allowlisted CIDRs, analyst approval). See
``app.services.response_executors`` and ``docs/LAB_RESPONSE.md``.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.core.db import session_scope
from app.core.events import Event, EventType
from app.models import Alert, ResponseAction
from app.models.enums import AlertStatus
from app.services.response_service import (
    approve_action,
    recommend_for_alert,
    reject_action,
)


class ResponseAgent(Agent):
    name = "agent.response"
    # Default policy. Real effects require explicit LAB config + analyst
    # approval and are enforced by the DB constraint, not just this flag.
    simulated_default: bool = True

    def register(self) -> None:
        self.bus.subscribe(EventType.ALERT_TRIAGED, self.on_alert_triaged)

    async def on_alert_triaged(self, event: Event) -> None:
        alert_id = event.payload.get("alert_id")
        if alert_id is None:
            return
        async with session_scope() as session:
            await self.respond_if_needed(session, int(alert_id))

    async def respond_if_needed(self, session: AsyncSession, alert_id: int) -> list[ResponseAction]:
        """Recommend actions iff the alert is TRIAGED with none yet.

        Idempotent on two guards (status + existing actions), so repeated
        ``alert.triaged`` events never create duplicate response actions. The
        synchronous pipeline advances the alert past TRIAGED itself, so this is a
        no-op for alerts it already handled.
        """
        alert = await session.get(Alert, alert_id)
        if alert is None or alert.status != AlertStatus.TRIAGED:
            return []
        existing = (
            await session.execute(
                select(func.count(ResponseAction.id)).where(ResponseAction.alert_id == alert_id)
            )
        ).scalar_one()
        if existing:
            return []
        actions = await self.recommend(session, alert, commit=True)
        self.logger.info("agent.response.recommended", alert_id=alert_id, n=len(actions))
        return actions

    async def recommend(
        self, session: AsyncSession, alert: Alert, *, commit: bool = True
    ) -> list[ResponseAction]:
        return await recommend_for_alert(session, alert, commit=commit)

    async def approve(
        self,
        session: AsyncSession,
        action: ResponseAction,
        *,
        analyst_id: str | None = None,
        note: str | None = None,
    ) -> ResponseAction:
        return await approve_action(session, action, analyst_id=analyst_id, note=note)

    async def reject(
        self,
        session: AsyncSession,
        action: ResponseAction,
        *,
        reason: str,
        analyst_id: str | None = None,
    ) -> ResponseAction:
        return await reject_action(session, action, reason=reason, analyst_id=analyst_id)
