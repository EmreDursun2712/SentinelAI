"""Query + transaction integration tests against real Postgres.

These drive the committing service functions end-to-end on a real engine:
* ingestion creates the job + event rows it claims to,
* detection persists alerts + decisions in one committed transaction,
* a mid-flight failure rolls back partial inserts (no bad partial state),
* response approve/reject persist the expected row + audit state,
* reporting persists JSONB ``summary`` and writes the markdown file safely.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.ingestion.csv_loader import RowResult
from app.ingestion.parser import ParsedFlow
from app.models import (
    AgentDecision,
    Alert,
    IncidentReport,
    IngestionJob,
    ModelVersion,
    NetworkEvent,
    ResponseAction,
)
from app.models.enums import (
    AgentName,
    AlertStatus,
    IncidentKind,
    IngestionStatus,
    ResponseActionType,
    ResponseStatus,
)
from app.services import ingestion_service
from app.services.detection_service import detect_events
from app.services.ingestion_service import ingest_csv
from app.services.model_registry import ModelBundle
from app.services.reporting_service import generate_alert_report
from app.services.response_service import approve_action, reject_action

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Ingestion: jobs + events.
# ---------------------------------------------------------------------------

_CSV = (
    "event_time,src_ip,dst_ip,dst_port,protocol,label,flow_duration\n"
    "2024-01-01 00:00:00,10.0.0.1,10.0.0.2,80,TCP,DDoS,123\n"
    "2024-01-01 00:00:01,10.0.0.3,10.0.0.4,443,TCP,BENIGN,45\n"
    "not-a-time,10.0.0.5,10.0.0.6,53,UDP,BENIGN,1\n"  # invalid row → counted, not stored
)


async def test_ingest_csv_creates_job_and_events(db_session: AsyncSession) -> None:
    summary = await ingest_csv(db_session, file=io.BytesIO(_CSV.encode()), source="test.csv")
    assert summary.status == IngestionStatus.COMPLETED
    assert summary.total_rows == 3
    assert summary.valid_rows == 2
    assert summary.invalid_rows == 1

    db_session.expire_all()  # force reads from the DB, not the identity map
    job = (
        await db_session.execute(select(IngestionJob).where(IngestionJob.id == summary.job_id))
    ).scalar_one()
    assert job.status == IngestionStatus.COMPLETED
    assert job.records_total == 3
    assert job.records_done == 2
    assert job.records_failed == 1
    assert job.completed_at is not None

    n_events = (
        await db_session.execute(
            select(func.count())
            .select_from(NetworkEvent)
            .where(NetworkEvent.ingestion_job_id == summary.job_id)
        )
    ).scalar_one()
    assert n_events == 2


async def test_failed_ingestion_leaves_no_partial_events(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash mid-stream rolls back flushed events; the job is recorded FAILED."""
    monkeypatch.setattr(ingestion_service, "BATCH_SIZE", 2)

    def exploding_stream(_file):
        for i in range(3):  # first 2 trigger a real flush (BATCH_SIZE=2), then boom
            yield RowResult(
                row_number=i + 1,
                parsed=ParsedFlow(
                    event_time=datetime(2024, 1, 1, tzinfo=UTC),
                    src_ip="10.9.9.1",
                    dst_ip="10.9.9.2",
                ),
                error=None,
            )
        raise RuntimeError("boom mid-stream")

    monkeypatch.setattr(ingestion_service, "stream_csv", exploding_stream)

    with pytest.raises(RuntimeError, match="boom mid-stream"):
        await ingest_csv(db_session, file=io.BytesIO(b"ignored"), source="will-fail.csv")

    db_session.expire_all()
    job = (
        await db_session.execute(select(IngestionJob).where(IngestionJob.source == "will-fail.csv"))
    ).scalar_one()
    assert job.status == IngestionStatus.FAILED
    assert job.error_message and "boom mid-stream" in job.error_message

    leftover = (
        await db_session.execute(
            select(func.count())
            .select_from(NetworkEvent)
            .where(NetworkEvent.ingestion_job_id == job.id)
        )
    ).scalar_one()
    assert leftover == 0, "rolled-back events must not survive a failed ingestion"


# ---------------------------------------------------------------------------
# Detection: alerts + decisions in one committed transaction.
# ---------------------------------------------------------------------------


class _FakePipeline:
    def __init__(self, rows: list[list[float]]) -> None:
        self._rows = rows

    def predict_proba(self, x) -> np.ndarray:
        return np.array(self._rows)


def _bundle(classes: list[str], rows: list[list[float]]) -> ModelBundle:
    return ModelBundle(
        pipeline=_FakePipeline(rows),
        metadata={"name": "itest", "version": "v1", "algorithm": "fake"},
        classes=classes,
        feature_order=["flow_duration", "total_fwd_packets"],
        name="itest",
        version="v1",
        algorithm="fake",
        artifact_dir=Path("/tmp/itest"),
        loaded_at=datetime.now(UTC),
    )


async def test_detection_persists_alerts_and_decisions(db_session: AsyncSession) -> None:
    e1 = NetworkEvent(
        event_time=datetime.now(UTC),
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        features={"flow_duration": 1500, "total_fwd_packets": 12},
    )
    e2 = NetworkEvent(
        event_time=datetime.now(UTC),
        src_ip="10.0.0.3",
        dst_ip="10.0.0.4",
        features={"flow_duration": 50, "total_fwd_packets": 4},
    )
    db_session.add_all([e1, e2])
    await db_session.flush()

    bundle = _bundle(classes=["BENIGN", "DDoS"], rows=[[0.1, 0.9], [0.8, 0.2]])
    preds = await detect_events(
        db_session,
        bundle,
        [e1, e2],
        threshold=0.5,
        benign_label="BENIGN",
        auto_triage=False,
        auto_respond=False,
    )
    assert [p.alert_created for p in preds] == [True, False]

    e1_id = e1.id  # capture before expiring (avoids async lazy-load on stale attrs)
    db_session.expire_all()
    alerts = (await db_session.execute(select(Alert))).scalars().all()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.prediction == "DDoS"
    assert alert.confidence == pytest.approx(0.9)
    assert alert.status == AlertStatus.NEW
    assert alert.event_id == e1_id

    decisions = (
        (await db_session.execute(select(AgentDecision).where(AgentDecision.alert_id == alert.id)))
        .scalars()
        .all()
    )
    assert [d.agent for d in decisions] == [AgentName.DETECTION]
    assert decisions[0].reasoning["model_name"] == "itest"

    # both events marked detected; an active model_versions row was created
    for e in (e1, e2):
        await db_session.refresh(e)
        assert e.detected_at is not None
    active = (
        (await db_session.execute(select(ModelVersion).where(ModelVersion.is_active.is_(True))))
        .scalars()
        .all()
    )
    assert len(active) == 1
    assert active[0].name == "itest"
    assert alert.model_version_id == active[0].id


# ---------------------------------------------------------------------------
# Response: approve / reject persistence + audit.
# ---------------------------------------------------------------------------


async def _pending_action(session: AsyncSession) -> tuple[Alert, ResponseAction]:
    alert = Alert(
        src_ip="10.5.5.1",
        dst_ip="10.5.5.2",
        prediction="DDoS",
        confidence=0.8,
        status=AlertStatus.AWAITING_ANALYST,
    )
    session.add(alert)
    await session.flush()
    action = ResponseAction(
        alert_id=alert.id,
        action_type=ResponseActionType.NOTIFY_ANALYST,
        status=ResponseStatus.PENDING,
        approval_required=True,
    )
    session.add(action)
    await session.flush()
    return alert, action


async def test_approve_action_executes_and_audits(db_session: AsyncSession) -> None:
    alert, action = await _pending_action(db_session)
    action_id, alert_id = action.id, alert.id
    await approve_action(db_session, action, analyst_id="ui-analyst")

    db_session.expire_all()
    refreshed = (
        await db_session.execute(select(ResponseAction).where(ResponseAction.id == action_id))
    ).scalar_one()
    assert refreshed.status == ResponseStatus.EXECUTED
    assert refreshed.executed is True
    assert refreshed.executed_at is not None
    assert refreshed.approved_by == "ui-analyst"

    audit = (
        (
            await db_session.execute(
                select(AgentDecision).where(
                    AgentDecision.alert_id == alert_id,
                    AgentDecision.agent == AgentName.ANALYST,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert audit[0].decision["verb"] == "approve"


async def test_reject_action_persists_reason_and_audits(db_session: AsyncSession) -> None:
    alert, action = await _pending_action(db_session)
    action_id, alert_id = action.id, alert.id
    await reject_action(db_session, action, reason="duplicate alert", analyst_id="ui-analyst")

    db_session.expire_all()
    refreshed = (
        await db_session.execute(select(ResponseAction).where(ResponseAction.id == action_id))
    ).scalar_one()
    assert refreshed.status == ResponseStatus.REJECTED
    assert refreshed.executed is False
    assert refreshed.rejection_reason == "duplicate alert"

    audit = (
        (
            await db_session.execute(
                select(AgentDecision).where(
                    AgentDecision.alert_id == alert_id,
                    AgentDecision.agent == AgentName.ANALYST,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert audit[0].decision["verb"] == "reject"


# ---------------------------------------------------------------------------
# Reporting: JSONB summary + markdown file on disk.
# ---------------------------------------------------------------------------


async def test_report_persists_jsonb_and_markdown_file(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SENTINEL_REPORTS_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        alert = Alert(
            src_ip="10.7.7.1",
            dst_ip="10.7.7.2",
            prediction="PortScan",
            confidence=0.77,
            status=AlertStatus.AUTO_RESPONDED,
        )
        db_session.add(alert)
        await db_session.flush()
        db_session.add(
            AgentDecision(
                alert_id=alert.id,
                agent=AgentName.DETECTION,
                decision={"predicted_label": "PortScan", "confidence": 0.77},
                reasoning={"threshold": 0.5, "class_probabilities": {"PortScan": 0.77}},
            )
        )
        await db_session.flush()

        report, packet = await generate_alert_report(db_session, alert)
        report_id, alert_id = report.id, alert.id

        db_session.expire_all()
        stored = (
            await db_session.execute(select(IncidentReport).where(IncidentReport.id == report_id))
        ).scalar_one()
        assert stored.kind == IncidentKind.PER_ALERT
        assert stored.alert_id == alert_id
        # JSONB round-trips as a dict with the expected structure.
        assert isinstance(stored.summary, dict)
        assert stored.summary["overview"]["alert_id"] == alert_id
        assert stored.summary["markdown"]

        # Markdown file was written to the configured dir and is readable.
        assert stored.md_path is not None
        md_file = Path(stored.md_path)
        assert md_file.exists()
        assert md_file.parent == tmp_path
        assert md_file.read_text(encoding="utf-8") == packet.markdown
    finally:
        get_settings.cache_clear()
