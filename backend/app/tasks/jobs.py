"""arq job functions + their testable cores.

Each ``*_task(ctx, task_id)`` is the arq entrypoint (registered in
``app.worker``); it opens a session and delegates to a ``run_*`` core that takes a
session + task_id. The cores read params from the ``Task`` row, drive the task
lifecycle (RUNNING → progress → terminal) via ``task_service``, and call the
existing async services — so the worker reuses the exact same business logic as
the synchronous API. Cores are import-light and unit/integration testable.

Failures are caught and recorded on the task (``mark_failed``) rather than raised,
so a bad job is observable instead of vanishing into an arq retry loop.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.models import Alert, ModelDriftSnapshot, Task
from app.services import drift_service, retention_service, task_service
from app.services.detection_service import detect_events, fetch_undetected_events
from app.services.model_registry import get_model_registry
from app.services.reporting_service import generate_alert_report, generate_daily_summary

logger = get_logger("worker.jobs")


# ---------------------------------------------------------------------------
# Cores (session + task_id). Testable directly.
# ---------------------------------------------------------------------------


async def run_detection(session: AsyncSession, task_id: str) -> None:
    task = await task_service.mark_running(session, task_id)
    if task is None:
        return
    try:
        limit = int(task.params.get("limit", 1000))
        bundle = get_model_registry().get()
        if bundle is None:
            await task_service.mark_failed(session, task_id, "Detection model is not loaded.")
            return
        settings = get_settings()
        events = await fetch_undetected_events(session, limit)
        await task_service.set_progress(session, task_id, 30)
        predictions = await detect_events(
            session,
            bundle,
            events,
            threshold=settings.detection_threshold,
            benign_label=settings.detection_benign_label,
            class_thresholds=settings.detection_class_thresholds,
        )
        await task_service.mark_succeeded(
            session,
            task_id,
            {
                "processed": len(predictions),
                "alerts_created": sum(1 for p in predictions if p.alert_created),
            },
        )
    except Exception as exc:  # record on the task, don't crash the worker
        await task_service.mark_failed(session, task_id, str(exc))


async def run_report_alert(session: AsyncSession, task_id: str) -> None:
    task = await task_service.mark_running(session, task_id)
    if task is None:
        return
    try:
        alert_id = int(task.params["alert_id"])
        alert = await session.get(Alert, alert_id)
        if alert is None:
            await task_service.mark_failed(session, task_id, f"Alert {alert_id} not found.")
            return
        report, _ = await generate_alert_report(session, alert, commit=True)
        await task_service.mark_succeeded(session, task_id, {"report_id": report.id})
    except Exception as exc:
        await task_service.mark_failed(session, task_id, str(exc))


async def run_daily_summary(session: AsyncSession, task_id: str) -> None:
    task = await task_service.mark_running(session, task_id)
    if task is None:
        return
    try:
        report, packet = await generate_daily_summary(session, None, commit=True)
        await task_service.mark_succeeded(
            session, task_id, {"report_id": report.id, "total_alerts": packet.total_alerts}
        )
    except Exception as exc:
        await task_service.mark_failed(session, task_id, str(exc))


async def run_drift(session: AsyncSession, task_id: str) -> None:
    task = await task_service.mark_running(session, task_id)
    if task is None:
        return
    try:
        window_hours = int(task.params.get("window_hours", 24))
        result = await drift_service.run_drift_check(session, window_hours=window_hours)
        snapshot = result.snapshot
        await task_service.mark_succeeded(
            session,
            task_id,
            {
                "available": result.available,
                "reason": result.reason,
                "drift_score": snapshot.drift_score if snapshot else None,
                "status": snapshot.status.value if snapshot else None,
            },
        )
    except Exception as exc:
        await task_service.mark_failed(session, task_id, str(exc))


async def run_retention_cleanup(session: AsyncSession, task_id: str) -> None:
    """Housekeeping (old terminal tasks + drift snapshots) plus the data
    retention policy (events/alerts/reports). Honors ``params.dry_run``.
    """
    task = await task_service.mark_running(session, task_id)
    if task is None:
        return
    try:
        dry_run = bool(task.params.get("dry_run", False))
        days = int(task.params.get("days", get_settings().retention_days))
        cutoff = datetime.now(UTC) - timedelta(days=max(1, days))

        from app.models.enums import TASK_TERMINAL_STATES

        task_conds = (
            Task.created_at < cutoff,
            Task.status.in_(list(TASK_TERMINAL_STATES)),
            Task.id != task_id,
        )
        tasks_matched = int(
            (
                await session.execute(select(func.count()).select_from(Task).where(*task_conds))
            ).scalar_one()
            or 0
        )
        snapshots_matched = int(
            (
                await session.execute(
                    select(func.count(ModelDriftSnapshot.id)).where(
                        ModelDriftSnapshot.created_at < cutoff
                    )
                )
            ).scalar_one()
            or 0
        )
        tasks_affected = snapshots_affected = 0
        if not dry_run:
            tasks_affected = int(
                (await session.execute(delete(Task).where(*task_conds))).rowcount or 0
            )
            snapshots_affected = int(
                (
                    await session.execute(
                        delete(ModelDriftSnapshot).where(ModelDriftSnapshot.created_at < cutoff)
                    )
                ).rowcount
                or 0
            )
            await session.commit()

        # Data retention policy (events/alerts/reports) — safe + dry-run aware.
        retention = await retention_service.apply_retention(session, dry_run=dry_run)

        await task_service.mark_succeeded(
            session,
            task_id,
            {
                "dry_run": dry_run,
                "cutoff": cutoff.isoformat(),
                "tasks": {"matched": tasks_matched, "affected": tasks_affected},
                "drift_snapshots": {
                    "matched": snapshots_matched,
                    "affected": snapshots_affected,
                },
                "retention": retention,
            },
        )
    except Exception as exc:
        await task_service.mark_failed(session, task_id, str(exc))


async def run_ml_retrain(session: AsyncSession, task_id: str) -> None:
    """Optional: retrain the detection model. Disabled unless explicitly enabled."""
    task = await task_service.mark_running(session, task_id)
    if task is None:
        return
    settings = get_settings()
    if not settings.ml_retrain_enabled:
        await task_service.mark_failed(
            session, task_id, "ML retrain is disabled (set SENTINEL_ML_RETRAIN_ENABLED=true)."
        )
        return
    try:
        samples = int(task.params.get("synthetic", 20000))
        result = await asyncio.to_thread(_retrain_sync, samples)
        get_model_registry().reload(settings.ml_artifacts_dir)
        await task_service.mark_succeeded(session, task_id, result)
    except Exception as exc:
        await task_service.mark_failed(session, task_id, f"retrain failed: {exc}")


def _retrain_sync(samples: int) -> dict:
    """Blocking training run (offloaded to a thread). Requires the ml package."""
    from ml.train import main as train_main

    train_main(["--synthetic", str(samples)])
    return {"synthetic": samples}


# ---------------------------------------------------------------------------
# arq entrypoints (ctx, task_id) — registered in app.worker.
# ---------------------------------------------------------------------------


async def detection_run_task(ctx: dict, task_id: str) -> None:
    async with session_scope() as session:
        await run_detection(session, task_id)


async def report_alert_task(ctx: dict, task_id: str) -> None:
    async with session_scope() as session:
        await run_report_alert(session, task_id)


async def daily_summary_task(ctx: dict, task_id: str) -> None:
    async with session_scope() as session:
        await run_daily_summary(session, task_id)


async def drift_run_task(ctx: dict, task_id: str) -> None:
    async with session_scope() as session:
        await run_drift(session, task_id)


async def retention_cleanup_task(ctx: dict, task_id: str) -> None:
    async with session_scope() as session:
        await run_retention_cleanup(session, task_id)


async def ml_retrain_task(ctx: dict, task_id: str) -> None:
    async with session_scope() as session:
        await run_ml_retrain(session, task_id)


async def notify_task(ctx: dict, payload: dict) -> None:
    """Fan an alert notification out to the configured external channels.

    Unlike the other jobs this carries its own ``payload`` (no ``Task`` row) —
    notifications are fire-and-forget, best-effort, and never surface as tracked
    background tasks.
    """
    from app.services.notification_service import NotificationPayload, dispatch

    await dispatch(get_settings(), NotificationPayload.from_dict(payload))
