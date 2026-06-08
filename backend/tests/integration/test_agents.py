"""Agent idempotency against real Postgres — the no-duplicate-processing guarantee.

These exercise the event-driven workflow handlers directly (with the savepoint
session) to prove repeated/duplicate events never re-process an alert.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.response import ResponseAgent
from app.agents.triage import TriageAgent
from app.core.events import EventBus
from app.models import Alert, ResponseAction
from app.models.enums import AlertStatus, Severity

pytestmark = pytest.mark.integration


async def _new_alert(db: AsyncSession, **overrides) -> Alert:
    data = dict(src_ip="10.1.1.1", dst_ip="10.2.2.2", prediction="DDoS", confidence=0.95)
    data.update(overrides)
    alert = Alert(**data)
    db.add(alert)
    await db.flush()
    return alert


async def _action_count(db: AsyncSession, alert_id: int) -> int:
    return (
        await db.execute(
            select(func.count(ResponseAction.id)).where(ResponseAction.alert_id == alert_id)
        )
    ).scalar_one()


async def test_triage_agent_triages_new_alert_once(db_session: AsyncSession) -> None:
    alert = await _new_alert(db_session, status=AlertStatus.NEW)
    agent = TriageAgent(EventBus())

    first = await agent.triage_if_new(db_session, alert.id)
    assert first is not None
    await db_session.refresh(alert)
    assert alert.status != AlertStatus.NEW  # triaged

    # A repeated alert.created (e.g. duplicate event) must NOT re-triage.
    second = await agent.triage_if_new(db_session, alert.id)
    assert second is None


async def test_triage_agent_skips_already_triaged(db_session: AsyncSession) -> None:
    # Mirrors the synchronous pipeline: alert already advanced past NEW.
    alert = await _new_alert(db_session, status=AlertStatus.TRIAGED, severity=Severity.HIGH)
    agent = TriageAgent(EventBus())
    assert await agent.triage_if_new(db_session, alert.id) is None


async def test_response_agent_no_duplicate_actions(db_session: AsyncSession) -> None:
    alert = await _new_alert(
        db_session,
        status=AlertStatus.TRIAGED,
        severity=Severity.HIGH,
        priority=80.0,
    )
    agent = ResponseAgent(EventBus())

    first = await agent.respond_if_needed(db_session, alert.id)
    count_after_first = await _action_count(db_session, alert.id)
    assert count_after_first == len(first)

    # Repeated alert.triaged must not create more actions (status moved + guard).
    second = await agent.respond_if_needed(db_session, alert.id)
    count_after_second = await _action_count(db_session, alert.id)
    assert second == []
    assert count_after_second == count_after_first


async def test_response_agent_skips_when_not_triaged(db_session: AsyncSession) -> None:
    alert = await _new_alert(db_session, status=AlertStatus.AUTO_RESPONDED)
    agent = ResponseAgent(EventBus())
    assert await agent.respond_if_needed(db_session, alert.id) == []
