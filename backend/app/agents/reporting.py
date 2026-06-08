"""Reporting agent.

Analyst-triggered by default. When ``SENTINEL_REPORTING_AUTO`` is enabled it
subscribes to ``alert.investigated`` and generates a per-alert report
automatically — idempotent: it skips alerts that already have one.
"""

from __future__ import annotations

from datetime import date as date_t

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.events import Event, EventType
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
        self.bus.subscribe(EventType.ALERT_INVESTIGATED, self.on_alert_investigated)

    async def on_alert_investigated(self, event: Event) -> None:
        if not get_settings().reporting_auto:
            return
        alert_id = event.payload.get("alert_id")
        if alert_id is None:
            return
        async with session_scope() as session:
            await self.report_if_needed(session, int(alert_id))

    async def report_if_needed(self, session: AsyncSession, alert_id: int) -> IncidentReport | None:
        """Generate a per-alert report iff none exists yet. Idempotent."""
        alert = await session.get(Alert, alert_id)
        if alert is None:
            return None
        if await get_latest_alert_report(session, alert_id) is not None:
            return None
        report, _ = await self.per_alert(session, alert, commit=True)
        self.logger.info("agent.reporting.auto_ran", alert_id=alert_id, report_id=report.id)
        return report

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

    async def latest_for_alert(self, session: AsyncSession, alert_id: int) -> IncidentReport | None:
        return await get_latest_alert_report(session, alert_id)
