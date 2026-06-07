"""Dashboard API — single endpoint that powers the SOC overview screen."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.models import Alert, NetworkEvent, ResponseAction
from app.models.enums import AlertStatus, ResponseStatus, Severity
from app.schemas.alert import AlertStatsOut, DashboardOverviewOut

router = APIRouter(prefix="/dashboard")


async def _group(session, col) -> dict[str, int]:
    rows = (await session.execute(select(col, func.count()).group_by(col))).all()
    return {
        (v.value if hasattr(v, "value") else (str(v) if v is not None else "UNASSIGNED")): int(c)
        for v, c in rows
    }


@router.get("/overview")
async def dashboard_overview(session: SessionDep) -> DashboardOverviewOut:
    """One round trip for every KPI + chart aggregation the dashboard needs."""
    total_events = int(
        (await session.execute(select(func.count(NetworkEvent.id)))).scalar_one() or 0
    )
    total_alerts = int((await session.execute(select(func.count(Alert.id)))).scalar_one() or 0)
    open_alerts = int(
        (
            await session.execute(
                select(func.count(Alert.id)).where(Alert.status != AlertStatus.CLOSED)
            )
        ).scalar_one()
        or 0
    )
    critical_alerts = int(
        (
            await session.execute(
                select(func.count(Alert.id)).where(Alert.severity == Severity.CRITICAL)
            )
        ).scalar_one()
        or 0
    )
    high_alerts = int(
        (
            await session.execute(
                select(func.count(Alert.id)).where(Alert.severity == Severity.HIGH)
            )
        ).scalar_one()
        or 0
    )
    pending_actions = int(
        (
            await session.execute(
                select(func.count(ResponseAction.id)).where(
                    ResponseAction.status == ResponseStatus.PENDING
                )
            )
        ).scalar_one()
        or 0
    )

    alerts = AlertStatsOut(
        total=total_alerts,
        by_status=await _group(session, Alert.status),
        by_severity=await _group(session, Alert.severity),
        by_disposition=await _group(session, Alert.disposition),
        by_prediction=await _group(session, Alert.prediction),
    )

    return DashboardOverviewOut(
        total_events=total_events,
        suspicious_events=total_alerts,
        open_alerts=open_alerts,
        critical_alerts=critical_alerts,
        high_alerts=high_alerts,
        pending_actions=pending_actions,
        alerts=alerts,
    )
