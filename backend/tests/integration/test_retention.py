"""Data-retention + soft-delete integration tests against real Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import count_for
from app.core.config import Settings
from app.models import Alert, IncidentReport, NetworkEvent
from app.models.enums import IncidentKind
from app.services import reporting_service, retention_service

pytestmark = pytest.mark.integration

OLD = datetime.now(UTC) - timedelta(days=400)
NEW = datetime.now(UTC)

# Retention enabled at 30 days for all three policies.
SETTINGS = Settings(
    retention_events_days=30,
    retention_alerts_days=30,
    retention_reports_days=30,
)


async def _seed(db: AsyncSession) -> dict:
    old_event = NetworkEvent(event_time=OLD, src_ip="10.0.0.1", dst_ip="10.0.0.2", created_at=OLD)
    new_event = NetworkEvent(event_time=NEW, src_ip="10.0.0.3", dst_ip="10.0.0.4", created_at=NEW)
    old_alert = Alert(
        src_ip="10.1.1.1", dst_ip="10.2.2.2", prediction="DDoS", confidence=0.9, created_at=OLD
    )
    new_alert = Alert(
        src_ip="10.1.1.3", dst_ip="10.2.2.4", prediction="DDoS", confidence=0.9, created_at=NEW
    )
    old_report = IncidentReport(
        kind=IncidentKind.PER_ALERT, title="old", summary={}, created_at=OLD
    )
    new_report = IncidentReport(
        kind=IncidentKind.PER_ALERT, title="new", summary={}, created_at=NEW
    )
    db.add_all([old_event, new_event, old_alert, new_alert, old_report, new_report])
    await db.flush()
    return {
        "old_event": old_event,
        "new_event": new_event,
        "old_alert": old_alert,
        "new_alert": new_alert,
        "old_report": old_report,
        "new_report": new_report,
    }


async def test_default_settings_delete_nothing(db_session: AsyncSession) -> None:
    rows = await _seed(db_session)
    # Default Settings have all retention days = 0 → disabled (safe).
    plan = await retention_service.apply_retention(db_session, settings=Settings(), dry_run=False)
    assert plan["events"]["enabled"] is False
    assert plan["alerts"]["enabled"] is False
    assert plan["reports"]["enabled"] is False
    assert await db_session.get(NetworkEvent, rows["old_event"].id) is not None


async def test_dry_run_reports_but_does_not_modify(db_session: AsyncSession) -> None:
    rows = await _seed(db_session)
    plan = await retention_service.apply_retention(db_session, settings=SETTINGS, dry_run=True)

    assert plan["dry_run"] is True
    assert plan["events"]["matched"] >= 1 and plan["events"]["affected"] == 0
    assert plan["alerts"]["matched"] >= 1 and plan["alerts"]["affected"] == 0
    assert plan["reports"]["matched"] >= 1 and plan["reports"]["affected"] == 0

    # Nothing changed.
    await db_session.refresh(rows["old_alert"])
    assert rows["old_alert"].archived_at is None
    assert await db_session.get(NetworkEvent, rows["old_event"].id) is not None


async def test_apply_hard_deletes_events_and_archives_alerts_reports(
    db_session: AsyncSession,
) -> None:
    rows = await _seed(db_session)
    res = await retention_service.apply_retention(db_session, settings=SETTINGS, dry_run=False)

    assert res["events"]["affected"] >= 1
    assert res["alerts"]["affected"] >= 1
    assert res["reports"]["affected"] >= 1

    # Old event hard-deleted; new event kept.
    assert await db_session.get(NetworkEvent, rows["old_event"].id) is None
    assert await db_session.get(NetworkEvent, rows["new_event"].id) is not None

    # Old alert/report soft-archived; new ones untouched.
    await db_session.refresh(rows["old_alert"])
    await db_session.refresh(rows["new_alert"])
    assert rows["old_alert"].archived_at is not None
    assert rows["new_alert"].archived_at is None


async def test_archived_rows_excluded_from_lists(db_session: AsyncSession) -> None:
    rows = await _seed(db_session)
    await retention_service.apply_retention(db_session, settings=SETTINGS, dry_run=False)

    # Active-alert count excludes the archived one.
    active_alerts = await count_for(db_session, select(Alert).where(Alert.archived_at.is_(None)))
    archived_id = rows["old_alert"].id
    active_ids = (
        (await db_session.execute(select(Alert.id).where(Alert.archived_at.is_(None))))
        .scalars()
        .all()
    )
    assert archived_id not in active_ids
    assert active_alerts == len(active_ids)

    # list_reports / count_reports exclude the archived report.
    listed = await reporting_service.list_reports(db_session)
    assert rows["old_report"].id not in {r.id for r in listed}
    assert rows["new_report"].id in {r.id for r in listed}
