"""Host attack-timeline integration tests against real Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, NetworkEvent, ResponseAction
from app.models.enums import (
    AlertStatus,
    ExecutionMode,
    ResponseActionType,
    ResponseStatus,
    Severity,
)
from app.services import timeline_service

pytestmark = pytest.mark.integration

HOST = "10.0.0.5"


async def _seed(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    db_session.add(
        NetworkEvent(
            event_time=now - timedelta(minutes=30),
            src_ip=HOST,
            dst_ip="10.0.0.10",
            protocol="TCP",
            features={"flow_duration": 5.0},
            label="PortScan",
        )
    )
    alert = Alert(
        src_ip=HOST,
        dst_ip="10.0.0.10",
        prediction="PortScan",
        confidence=0.88,
        severity=Severity.HIGH,
        priority=7.5,
        status=AlertStatus.TRIAGED,
        triaged_at=now - timedelta(minutes=20),
    )
    db_session.add(alert)
    await db_session.flush()
    db_session.add(
        ResponseAction(
            alert_id=alert.id,
            action_type=ResponseActionType.BLOCK_IP,
            status=ResponseStatus.EXECUTED,
            approval_required=False,
            executed=True,
            simulated=True,
            execution_mode=ExecutionMode.SIMULATED,
            executed_at=now - timedelta(minutes=19),
        )
    )
    await db_session.commit()


async def test_host_timeline_merges_flow_alert_response(db_session: AsyncSession) -> None:
    await _seed(db_session)
    data = await timeline_service.host_timeline(db_session, HOST, window_hours=24)

    kinds = {it["kind"] for it in data["items"]}
    # flow + alert + triage + response all present.
    assert {"flow", "alert", "triage", "response"} <= kinds
    # Newest-first ordering.
    ts = [it["timestamp"] for it in data["items"]]
    assert ts == sorted(ts, reverse=True)

    s = data["summary"]
    assert s["ip"] == HOST
    assert s["alert_count"] == 1
    assert s["event_count"] == 1
    assert s["response_count"] == 1
    assert s["max_severity"] == "HIGH"
    assert "PortScan" in s["families"]


async def test_host_timeline_empty_for_unknown_ip(db_session: AsyncSession) -> None:
    await _seed(db_session)
    data = await timeline_service.host_timeline(db_session, "203.0.113.99", window_hours=24)
    assert data["items"] == []
    assert data["summary"]["alert_count"] == 0
