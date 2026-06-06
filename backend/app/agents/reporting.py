"""Reporting agent — thin wrapper around the reporting service."""

from __future__ import annotations

from datetime import date as date_t

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.models import Alert, IncidentReport
from app.schemas.reporting import AlertReportPacket, DailySummaryPacket
from app.services.reporting_service import (
    generate_alert_report,
    generate_daily_summary,
    get_latest_alert_report,
)


class ReportingAgent(Agent):
    name = "agent.reporting"

    def register(self) -> None:
        # Triggered explicitly from the API; event-bus subscription will land
        # alongside the agent runtime.
        return None

    async def per_alert(
        self,
        session: AsyncSession,
        alert: Alert,
        *,
        commit: bool = True,
    ) -> tuple[IncidentReport, AlertReportPacket]:
        return await generate_alert_report(session, alert, commit=commit)

    async def daily(
        self,
        session: AsyncSession,
        target_date: date_t | None = None,
        *,
        commit: bool = True,
    ) -> tuple[IncidentReport, DailySummaryPacket]:
        return await generate_daily_summary(session, target_date, commit=commit)

    async def latest_for_alert(
        self, session: AsyncSession, alert_id: int
    ) -> IncidentReport | None:
        return await get_latest_alert_report(session, alert_id)
