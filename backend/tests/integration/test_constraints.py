"""Database constraint integration tests against real Postgres.

These verify the guarantees that only a real engine can enforce:
* the ethics CHECK on ``response_actions`` (simulated unless LAB),
* the ``confidence`` and ``priority`` range CHECKs on ``alerts``,
* FK ``ON DELETE CASCADE`` and ``ON DELETE SET NULL`` behavior,
* the partial unique "only one active model" index + name/version uniqueness.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentDecision,
    Alert,
    AlertArtifact,
    IngestionJob,
    ModelVersion,
    NetworkEvent,
    ResponseAction,
)
from app.models.enums import (
    AgentName,
    ArtifactKind,
    ExecutionMode,
    IngestionKind,
    IngestionStatus,
    ResponseActionType,
    ResponseStatus,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Small builders for valid parent rows.
# ---------------------------------------------------------------------------


async def _make_alert(session: AsyncSession, **overrides) -> Alert:
    data = dict(src_ip="10.1.1.1", dst_ip="10.2.2.2", prediction="DDoS", confidence=0.9)
    data.update(overrides)
    alert = Alert(**data)
    session.add(alert)
    await session.flush()
    return alert


async def _make_event(session: AsyncSession, **overrides) -> NetworkEvent:
    from datetime import UTC, datetime

    data = dict(event_time=datetime.now(UTC), src_ip="10.1.1.1", dst_ip="10.2.2.2")
    data.update(overrides)
    event = NetworkEvent(**data)
    session.add(event)
    await session.flush()
    return event


async def _make_model_version(session: AsyncSession, **overrides) -> ModelVersion:
    data = dict(name="rf", version="v1", algorithm="random_forest", artifact_path="/tmp/x")
    data.update(overrides)
    mv = ModelVersion(**data)
    session.add(mv)
    await session.flush()
    return mv


# ---------------------------------------------------------------------------
# response_actions: simulated / execution-mode CHECK.
# ---------------------------------------------------------------------------


async def test_response_action_real_in_simulated_mode_is_rejected(db_session: AsyncSession) -> None:
    """simulated=False with execution_mode=SIMULATED violates the ethics CHECK."""
    alert = await _make_alert(db_session)
    bad = ResponseAction(
        alert_id=alert.id,
        action_type=ResponseActionType.BLOCK_IP,
        simulated=False,
        execution_mode=ExecutionMode.SIMULATED,
        status=ResponseStatus.PENDING,
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(bad)
            await db_session.flush()


async def test_response_action_real_in_lab_mode_is_allowed(db_session: AsyncSession) -> None:
    """simulated=False is permitted only when execution_mode=LAB."""
    alert = await _make_alert(db_session)
    ok = ResponseAction(
        alert_id=alert.id,
        action_type=ResponseActionType.BLOCK_IP,
        simulated=False,
        execution_mode=ExecutionMode.LAB,
        status=ResponseStatus.PENDING,
    )
    db_session.add(ok)
    await db_session.flush()
    assert ok.id is not None


async def test_response_action_simulated_default_is_allowed(db_session: AsyncSession) -> None:
    alert = await _make_alert(db_session)
    ok = ResponseAction(
        alert_id=alert.id,
        action_type=ResponseActionType.NOTIFY_ANALYST,
        simulated=True,
        execution_mode=ExecutionMode.SIMULATED,
    )
    db_session.add(ok)
    await db_session.flush()
    assert ok.id is not None


# ---------------------------------------------------------------------------
# alerts: confidence + priority range CHECKs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 5.0])
async def test_alert_confidence_out_of_range_rejected(
    db_session: AsyncSession, confidence: float
) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _make_alert(db_session, confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
async def test_alert_confidence_in_range_allowed(
    db_session: AsyncSession, confidence: float
) -> None:
    alert = await _make_alert(db_session, confidence=confidence)
    assert alert.id is not None


@pytest.mark.parametrize("priority", [-1.0, 100.01, 250.0])
async def test_alert_priority_out_of_range_rejected(
    db_session: AsyncSession, priority: float
) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _make_alert(db_session, priority=priority)


async def test_alert_priority_null_and_in_range_allowed(db_session: AsyncSession) -> None:
    a = await _make_alert(db_session, priority=None)
    b = await _make_alert(db_session, priority=50.0)
    assert a.id is not None and b.id is not None


# ---------------------------------------------------------------------------
# FK ON DELETE behavior.
# ---------------------------------------------------------------------------


async def test_delete_alert_cascades_to_children(db_session: AsyncSession) -> None:
    """Deleting an alert removes its decisions, actions, and artifacts (DB CASCADE)."""
    alert = await _make_alert(db_session)
    db_session.add(AgentDecision(alert_id=alert.id, agent=AgentName.DETECTION, decision={}))
    db_session.add(ResponseAction(alert_id=alert.id, action_type=ResponseActionType.NOTIFY_ANALYST))
    db_session.add(
        AlertArtifact(alert_id=alert.id, kind=ArtifactKind.INVESTIGATION_PACKET, data={})
    )
    await db_session.flush()

    # Core DELETE bypasses ORM cascades, so this exercises the DB ON DELETE rule.
    await db_session.execute(delete(Alert).where(Alert.id == alert.id))
    await db_session.flush()

    for model in (AgentDecision, ResponseAction, AlertArtifact):
        remaining = (
            await db_session.execute(
                select(func.count()).select_from(model).where(model.alert_id == alert.id)
            )
        ).scalar_one()
        assert remaining == 0, f"{model.__name__} rows survived alert delete"


async def test_delete_event_sets_alert_event_id_null(db_session: AsyncSession) -> None:
    event = await _make_event(db_session)
    alert = await _make_alert(db_session, event_id=event.id)

    await db_session.execute(delete(NetworkEvent).where(NetworkEvent.id == event.id))
    await db_session.flush()
    await db_session.refresh(alert)
    assert alert.event_id is None  # SET NULL, alert preserved


async def test_delete_model_version_sets_alert_fk_null(db_session: AsyncSession) -> None:
    mv = await _make_model_version(db_session)
    alert = await _make_alert(db_session, model_version_id=mv.id)

    await db_session.execute(delete(ModelVersion).where(ModelVersion.id == mv.id))
    await db_session.flush()
    await db_session.refresh(alert)
    assert alert.model_version_id is None


async def test_delete_ingestion_job_sets_event_fk_null(db_session: AsyncSession) -> None:
    job = IngestionJob(kind=IngestionKind.REPLAY, source="x", status=IngestionStatus.COMPLETED)
    db_session.add(job)
    await db_session.flush()
    event = await _make_event(db_session, ingestion_job_id=job.id)

    await db_session.execute(delete(IngestionJob).where(IngestionJob.id == job.id))
    await db_session.flush()
    await db_session.refresh(event)
    assert event.ingestion_job_id is None


async def test_delete_decision_sets_response_action_fk_null(db_session: AsyncSession) -> None:
    alert = await _make_alert(db_session)
    decision = AgentDecision(alert_id=alert.id, agent=AgentName.RESPONSE, decision={})
    db_session.add(decision)
    await db_session.flush()
    action = ResponseAction(
        alert_id=alert.id,
        decision_id=decision.id,
        action_type=ResponseActionType.NOTIFY_ANALYST,
    )
    db_session.add(action)
    await db_session.flush()

    await db_session.execute(delete(AgentDecision).where(AgentDecision.id == decision.id))
    await db_session.flush()
    await db_session.refresh(action)
    assert action.decision_id is None  # SET NULL keeps the action row


# ---------------------------------------------------------------------------
# model_versions: only-one-active + name/version uniqueness.
# ---------------------------------------------------------------------------


async def test_only_one_active_model_version(db_session: AsyncSession) -> None:
    await _make_model_version(db_session, name="rf", version="v1", is_active=True)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _make_model_version(db_session, name="rf", version="v2", is_active=True)


async def test_multiple_inactive_model_versions_allowed(db_session: AsyncSession) -> None:
    a = await _make_model_version(db_session, name="rf", version="v1", is_active=False)
    b = await _make_model_version(db_session, name="rf", version="v2", is_active=False)
    assert a.id != b.id


async def test_model_version_name_version_unique(db_session: AsyncSession) -> None:
    await _make_model_version(db_session, name="rf", version="v1")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _make_model_version(db_session, name="rf", version="v1")
