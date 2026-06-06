"""Response agent — thin wrapper around the response service.

Ethics: every ``ResponseAction`` row created by this agent has
``simulated=True`` enforced at the DB layer via the ``ck_response_actions_
simulated_only`` CHECK constraint. There is no code path in the project that
contacts a real firewall, EDR, or ticketing system.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.models import Alert, ResponseAction
from app.services.response_service import (
    approve_action,
    recommend_for_alert,
    reject_action,
)


class ResponseAgent(Agent):
    name = "agent.response"
    simulated_only: bool = True  # hard-coded by policy — do not flip.

    def register(self) -> None:
        # The Detection service invokes recommend_for_alert directly; the
        # event-bus subscription lands when the agent runtime is wired up.
        return None

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
        return await reject_action(
            session, action, reason=reason, analyst_id=analyst_id
        )
