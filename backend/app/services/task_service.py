"""Task service: create/enqueue background jobs and track their lifecycle.

The DB ``Task`` row is the source of truth. The API creates a PENDING row and
enqueues the matching arq function (which receives only the ``task_id`` and reads
its params from the row). The worker drives the row through RUNNING → terminal,
emitting a ``task.updated`` WebSocket event at each transition (cross-worker via
the Redis broadcaster, so the originating API worker's clients see updates).

The lifecycle helpers are idempotent on terminal state — a task already in a
terminal state is never moved again, so duplicate/retried processing is safe.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import EventType, publish_event
from app.core.logging import get_logger
from app.core.queue import get_task_queue
from app.models import Task
from app.models.enums import TASK_TERMINAL_STATES, TaskKind, TaskStatus

logger = get_logger(__name__)

# TaskKind → arq worker function name (must match app.worker registrations).
KIND_FUNCTION: dict[TaskKind, str] = {
    TaskKind.DETECTION_RUN: "detection_run_task",
    TaskKind.REPORT_ALERT: "report_alert_task",
    TaskKind.DAILY_SUMMARY: "daily_summary_task",
    TaskKind.DRIFT_RUN: "drift_run_task",
    TaskKind.RETENTION_CLEANUP: "retention_cleanup_task",
    TaskKind.ML_RETRAIN: "ml_retrain_task",
}


async def _emit(task: Task) -> None:
    await publish_event(
        EventType.TASK_UPDATED,
        {
            "task_id": task.id,
            "kind": task.kind.value,
            "status": task.status.value,
            "progress": task.progress,
        },
    )


async def create_task(
    session: AsyncSession,
    *,
    kind: TaskKind,
    params: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> Task:
    """Persist a PENDING task and enqueue it. Returns the row (commit included)."""
    task = Task(
        id=str(uuid4()),
        kind=kind,
        status=TaskStatus.PENDING,
        params=params or {},
        created_by=created_by,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    job_id = await get_task_queue().enqueue(KIND_FUNCTION[kind], task.id)
    logger.info("task.created", task_id=task.id, kind=kind.value, job_id=job_id, by=created_by)
    await _emit(task)
    return task


async def get_task(session: AsyncSession, task_id: str) -> Task | None:
    return await session.get(Task, task_id)


def _tasks_filtered(created_by: str | None, status: TaskStatus | None, kind: TaskKind | None):
    stmt = select(Task)
    if created_by is not None:
        stmt = stmt.where(Task.created_by == created_by)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if kind is not None:
        stmt = stmt.where(Task.kind == kind)
    return stmt


async def list_tasks(
    session: AsyncSession,
    *,
    created_by: str | None = None,
    status: TaskStatus | None = None,
    kind: TaskKind | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Task]:
    """List tasks newest-first. ``created_by`` filters to one owner (RBAC)."""
    stmt = (
        _tasks_filtered(created_by, status, kind)
        .order_by(Task.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_tasks(
    session: AsyncSession,
    *,
    created_by: str | None = None,
    status: TaskStatus | None = None,
    kind: TaskKind | None = None,
) -> int:
    from app.api.pagination import count_for

    return await count_for(session, _tasks_filtered(created_by, status, kind))


# ---------------------------------------------------------------------------
# Lifecycle transitions (called by the worker). All commit + emit.
# ---------------------------------------------------------------------------


async def mark_running(session: AsyncSession, task_id: str) -> Task | None:
    task = await session.get(Task, task_id)
    if task is None or task.status in TASK_TERMINAL_STATES:
        return task
    task.status = TaskStatus.RUNNING
    task.started_at = task.started_at or datetime.now(UTC)
    task.progress = max(task.progress, 1)
    await session.commit()
    await _emit(task)
    return task


async def set_progress(session: AsyncSession, task_id: str, progress: int) -> Task | None:
    task = await session.get(Task, task_id)
    if task is None or task.status in TASK_TERMINAL_STATES:
        return task
    task.progress = max(0, min(100, int(progress)))
    await session.commit()
    await _emit(task)
    return task


async def mark_succeeded(
    session: AsyncSession, task_id: str, result: dict[str, Any] | None = None
) -> Task | None:
    task = await session.get(Task, task_id)
    if task is None or task.status in TASK_TERMINAL_STATES:
        return task
    task.status = TaskStatus.SUCCEEDED
    task.progress = 100
    task.result = result or {}
    task.finished_at = datetime.now(UTC)
    await session.commit()
    logger.info("task.succeeded", task_id=task_id, kind=task.kind.value)
    await _emit(task)
    return task


async def mark_failed(session: AsyncSession, task_id: str, error: str) -> Task | None:
    task = await session.get(Task, task_id)
    if task is None or task.status in TASK_TERMINAL_STATES:
        return task
    task.status = TaskStatus.FAILED
    task.error = (error or "")[:2000]
    task.finished_at = datetime.now(UTC)
    await session.commit()
    logger.warning("task.failed", task_id=task_id, kind=task.kind.value, error=task.error)
    await _emit(task)
    return task


async def mark_cancelled(session: AsyncSession, task_id: str) -> Task | None:
    task = await session.get(Task, task_id)
    if task is None or task.status in TASK_TERMINAL_STATES:
        return task
    task.status = TaskStatus.CANCELLED
    task.finished_at = datetime.now(UTC)
    await session.commit()
    await _emit(task)
    return task
