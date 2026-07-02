"""Unified audit trail integration tests against real Postgres.

Seeds one event from each audit source (login, model activation, analyst
disposition, response approval) and asserts the merged feed surfaces them all,
newest-first, with category filtering working.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentDecision,
    Alert,
    AuthSession,
    ModelActivation,
    ModelVersion,
    ResponseAction,
    User,
)
from app.models.enums import (
    AgentName,
    AlertStatus,
    ExecutionMode,
    ResponseActionType,
    ResponseStatus,
    Role,
)
from app.services import audit_service

pytestmark = pytest.mark.integration


async def _seed(db_session: AsyncSession) -> int:
    now = datetime.now(UTC)
    user = User(username="alice", password_hash="x", role=Role.ANALYST, is_active=True)
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        AuthSession(
            user_id=user.id,
            token_hash="h" * 64,
            expires_at=now + timedelta(days=1),
            created_at=now - timedelta(minutes=30),
            ip="10.0.0.5",
        )
    )

    mv = ModelVersion(
        name="m",
        version="v1",
        algorithm="rf",
        classes=["BENIGN"],
        feature_order=["a"],
        metrics={},
        artifact_path="/tmp/m",
        is_active=True,
    )
    db_session.add(mv)
    await db_session.flush()
    db_session.add(
        ModelActivation(
            model_version_id=mv.id,
            action="activate",
            actor="alice",
            reason="better F1",
            created_at=now - timedelta(minutes=20),
        )
    )

    alert = Alert(
        src_ip="1.2.3.4",
        dst_ip="5.6.7.8",
        prediction="DDoS",
        confidence=0.9,
        status=AlertStatus.NEW,
    )
    db_session.add(alert)
    await db_session.flush()
    db_session.add(
        AgentDecision(
            alert_id=alert.id,
            agent=AgentName.ANALYST,
            decision={"disposition_from": "OPEN", "disposition_to": "CONFIRMED"},
            reasoning={"analyst_id": "alice", "note": "true positive"},
            created_at=now - timedelta(minutes=10),
        )
    )
    action = ResponseAction(
        alert_id=alert.id,
        action_type=ResponseActionType.BLOCK_IP,
        status=ResponseStatus.EXECUTED,
        approval_required=True,
        executed=True,
        approved_by="alice",
        simulated=True,
        execution_mode=ExecutionMode.SIMULATED,
    )
    db_session.add(action)
    await db_session.commit()
    return alert.id


async def test_audit_merges_all_sources(db_session: AsyncSession) -> None:
    await _seed(db_session)
    entries, has_more = await audit_service.list_audit(db_session, limit=50)

    categories = {e.category for e in entries}
    assert {"auth", "model", "analyst", "response"} <= categories
    assert not has_more
    # Newest-first ordering holds across the merged sources.
    ts = [e.timestamp for e in entries]
    assert ts == sorted(ts, reverse=True)
    # The analyst disposition renders its verb + target.
    analyst = next(e for e in entries if e.category == "analyst")
    assert "CONFIRMED" in analyst.action
    assert analyst.actor == "alice"


async def test_audit_category_filter(db_session: AsyncSession) -> None:
    await _seed(db_session)
    entries, _ = await audit_service.list_audit(db_session, categories=["model"], limit=50)
    assert entries
    assert all(e.category == "model" for e in entries)
