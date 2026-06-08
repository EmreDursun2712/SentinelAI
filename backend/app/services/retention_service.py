"""Data retention: age out old events / alerts / reports per policy.

Policy is age cutoffs in days from settings; **0 disables** a policy, so the
default config deletes/archives nothing (safe by default). Supports **dry-run**
(count only, no writes). See docs/DATA_RETENTION.md.

Deletion strategy:
* **events** — hard-deleted. ``alerts.event_id`` is ``ON DELETE SET NULL``, so an
  alert that referenced a pruned event keeps its row (event_id becomes NULL).
* **alerts / reports** — **soft-deleted** (``archived_at`` set) to preserve the
  audit trail; archived rows are hidden from default list endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models import Alert, IncidentReport, NetworkEvent

logger = get_logger(__name__)


async def _count(session: AsyncSession, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    for cond in conditions:
        stmt = stmt.where(cond)
    return int((await session.execute(stmt)).scalar_one() or 0)


def _disabled() -> dict[str, Any]:
    return {"enabled": False, "matched": 0, "affected": 0}


async def apply_retention(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply (or, with ``dry_run``, just report) the retention policy.

    Returns a per-policy summary: ``matched`` (rows the policy targets) and
    ``affected`` (rows actually deleted/archived; 0 on a dry run).
    """
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    out: dict[str, Any] = {
        "dry_run": dry_run,
        "events": _disabled(),
        "alerts": _disabled(),
        "reports": _disabled(),
    }

    # --- events: hard delete (FK SET NULL on dependent alerts) ---
    if settings.retention_events_days > 0:
        cutoff = now - timedelta(days=settings.retention_events_days)
        matched = await _count(session, NetworkEvent, NetworkEvent.created_at < cutoff)
        affected = 0
        if not dry_run and matched:
            res = await session.execute(
                delete(NetworkEvent).where(NetworkEvent.created_at < cutoff)
            )
            affected = int(res.rowcount or 0)
        out["events"] = {
            "enabled": True,
            "action": "hard_delete",
            "days": settings.retention_events_days,
            "cutoff": cutoff.isoformat(),
            "matched": matched,
            "affected": affected,
        }

    # --- alerts: soft archive ---
    if settings.retention_alerts_days > 0:
        cutoff = now - timedelta(days=settings.retention_alerts_days)
        conds = (Alert.created_at < cutoff, Alert.archived_at.is_(None))
        matched = await _count(session, Alert, *conds)
        affected = 0
        if not dry_run and matched:
            res = await session.execute(update(Alert).where(*conds).values(archived_at=now))
            affected = int(res.rowcount or 0)
        out["alerts"] = {
            "enabled": True,
            "action": "soft_archive",
            "days": settings.retention_alerts_days,
            "cutoff": cutoff.isoformat(),
            "matched": matched,
            "affected": affected,
        }

    # --- reports: soft archive ---
    if settings.retention_reports_days > 0:
        cutoff = now - timedelta(days=settings.retention_reports_days)
        conds = (IncidentReport.created_at < cutoff, IncidentReport.archived_at.is_(None))
        matched = await _count(session, IncidentReport, *conds)
        affected = 0
        if not dry_run and matched:
            res = await session.execute(
                update(IncidentReport).where(*conds).values(archived_at=now)
            )
            affected = int(res.rowcount or 0)
        out["reports"] = {
            "enabled": True,
            "action": "soft_archive",
            "days": settings.retention_reports_days,
            "cutoff": cutoff.isoformat(),
            "matched": matched,
            "affected": affected,
        }

    if not dry_run:
        await session.commit()
    logger.info("retention.applied", dry_run=dry_run, summary=out)
    return out
