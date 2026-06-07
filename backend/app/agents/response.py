"""Response agent — thin wrapper around the response service.

Ethics: actions are ``simulated`` by default. The DB CHECK
``ck_response_actions_simulated_unless_lab`` makes a non-simulated row possible
ONLY in ``execution_mode='LAB'`` — and LAB is itself disabled unless explicitly,
safely configured (allowlisted CIDRs, analyst approval). See
``app.services.response_executors`` and ``docs/LAB_RESPONSE.md``.
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
    # Default policy. Real effects require explicit LAB config + analyst
    # approval and are enforced by the DB constraint, not just this flag.
    simulated_default: bool = True

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
