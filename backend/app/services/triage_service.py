"""Triage Agent service.

Two entry points:

* ``triage_alert`` — compute severity + priority for one alert and persist
  the decision. Called both inline from the Detection service (commit=False)
  and from ``POST /api/v1/alerts/{id}/triage`` (commit=True).
* ``update_disposition`` — analyst feedback path. Updates the verdict and
  appends an ``ANALYST`` row to ``agent_decisions``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import EventType, publish_event
from app.core.logging import get_logger
from app.models import AgentDecision, Alert
from app.models.enums import (
    AgentName,
    AlertDisposition,
    AlertStatus,
    Severity,
)
from app.services.triage_rules import TriageScore, compute_score

logger = get_logger(__name__)

# Window over which we count "recent activity from the same src_ip".
VOLUME_WINDOW_MINUTES = 15


async def _recent_src_ip_count(
    session: AsyncSession,
    src_ip: str,
    *,
    window_minutes: int,
    exclude_id: int | None = None,
) -> int:
    """Count alerts from the same src_ip in the last ``window_minutes``."""
    since = datetime.now(UTC) - timedelta(minutes=window_minutes)
    stmt = select(func.count(Alert.id)).where(
        Alert.src_ip == src_ip,
        Alert.created_at >= since,
    )
    if exclude_id is not None:
        stmt = stmt.where(Alert.id != exclude_id)
    return int((await session.execute(stmt)).scalar_one() or 0)


async def triage_alert(
    session: AsyncSession,
    alert: Alert,
    *,
    window_minutes: int = VOLUME_WINDOW_MINUTES,
    commit: bool = True,
) -> TriageScore:
    """Compute the score, mutate the alert, append an audit row.

    ``commit=False`` keeps the work inside whatever transaction the caller
    started — the Detection service uses this to keep alert creation +
    triage in one atomic step.
    """
    recent_count = await _recent_src_ip_count(
        session,
        alert.src_ip,
        window_minutes=window_minutes,
        exclude_id=alert.id,
    )

    score = compute_score(
        family=alert.prediction,
        confidence=alert.confidence,
        dst_port=alert.dst_port,
        recent_count=recent_count,
    )

    alert.severity = Severity(score.severity)
    alert.priority = score.priority
    alert.triaged_at = datetime.now(UTC)
    if alert.status == AlertStatus.NEW:
        alert.status = AlertStatus.TRIAGED

    decision = AgentDecision(
        alert_id=alert.id,
        agent=AgentName.TRIAGE,
        decision={
            "severity": score.severity,
            "priority": score.priority,
            "recent_count": recent_count,
        },
        reasoning={
            "factors": {
                "family": score.family,
                "family_score": score.family_score,
                "confidence_score": score.confidence_score,
                "dst_port": score.dst_port,
                "port_score": score.port_score,
                "volume_score": score.volume_score,
            },
            "component_weights": score.component_weights,
            "explanations": score.explanations,
            "window_minutes": window_minutes,
        },
    )
    session.add(decision)

    if commit:
        await session.commit()
        await session.refresh(alert)

    logger.info(
        "triage.completed",
        alert_id=alert.id,
        severity=score.severity,
        priority=score.priority,
        recent_count=recent_count,
    )
    # Only the committing (endpoint) path broadcasts; when commit=False the
    # Detection orchestrator owns the broadcast after its own commit.
    if commit:
        await publish_event(
            EventType.ALERT_TRIAGED,
            {"alert_id": alert.id, "severity": score.severity, "priority": score.priority},
        )
    return score


async def close_alert(
    session: AsyncSession,
    alert: Alert,
    *,
    analyst_id: str | None = None,
    note: str | None = None,
) -> Alert:
    """Mark an alert CLOSED and append an ``ANALYST`` audit row.

    Idempotent: if the alert is already CLOSED, returns unchanged without
    spamming the audit log with duplicate close events.
    """
    if alert.status == AlertStatus.CLOSED:
        return alert

    alert.status = AlertStatus.CLOSED
    if alert.closed_at is None:
        alert.closed_at = datetime.now(UTC)

    decision = AgentDecision(
        alert_id=alert.id,
        agent=AgentName.ANALYST,
        decision={"verb": "close"},
        reasoning={"analyst_id": analyst_id, "note": (note or "").strip() or None},
    )
    session.add(decision)

    await session.commit()
    await session.refresh(alert)

    logger.info("alert.closed", alert_id=alert.id, analyst_id=analyst_id)
    await publish_event(EventType.ALERT_CLOSED, {"alert_id": alert.id})
    return alert


async def update_disposition(
    session: AsyncSession,
    alert: Alert,
    new_disposition: AlertDisposition,
    *,
    analyst_id: str | None = None,
    note: str | None = None,
) -> Alert:
    """Apply an analyst verdict. Auto-closes the workflow for terminal verdicts."""
    previous = alert.disposition
    alert.disposition = new_disposition

    # FALSE_POSITIVE and RESOLVED are terminal — close the workflow too.
    terminal = {AlertDisposition.FALSE_POSITIVE, AlertDisposition.RESOLVED}
    if new_disposition in terminal:
        if alert.status != AlertStatus.CLOSED:
            alert.status = AlertStatus.CLOSED
        if alert.closed_at is None:
            alert.closed_at = datetime.now(UTC)

    decision = AgentDecision(
        alert_id=alert.id,
        agent=AgentName.ANALYST,
        decision={
            "disposition_from": previous.value if hasattr(previous, "value") else str(previous),
            "disposition_to": new_disposition.value,
        },
        reasoning={
            "analyst_id": analyst_id,
            "note": (note or "").strip() or None,
        },
    )
    session.add(decision)

    await session.commit()
    await session.refresh(alert)

    logger.info(
        "disposition.updated",
        alert_id=alert.id,
        from_=previous.value if hasattr(previous, "value") else str(previous),
        to=new_disposition.value,
        analyst_id=analyst_id,
    )
    await publish_event(
        EventType.ALERT_DISPOSITION_UPDATED,
        {
            "alert_id": alert.id,
            "disposition": new_disposition.value,
            "status": alert.status.value,
        },
    )
    if new_disposition in terminal:
        await publish_event(EventType.ALERT_CLOSED, {"alert_id": alert.id})
    return alert
