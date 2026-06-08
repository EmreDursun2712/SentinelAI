"""Task service + worker-job integration tests against real Postgres.

The queue defaults to NullTaskQueue here (no Redis), so ``create_task`` persists
a PENDING row without enqueuing; the worker-job *cores* are then driven directly
against the savepoint session to verify status transitions end-to-end.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TaskKind, TaskStatus
from app.services import task_service
from app.tasks import jobs

pytestmark = pytest.mark.integration


async def test_create_get_and_list_with_rbac(db_session: AsyncSession) -> None:
    a = await task_service.create_task(
        db_session, kind=TaskKind.DRIFT_RUN, params={"window_hours": 12}, created_by="alice"
    )
    await task_service.create_task(db_session, kind=TaskKind.DAILY_SUMMARY, created_by="bob")

    assert a.status == TaskStatus.PENDING
    fetched = await task_service.get_task(db_session, a.id)
    assert fetched is not None and fetched.params["window_hours"] == 12

    alice_tasks = await task_service.list_tasks(db_session, created_by="alice")
    assert alice_tasks and all(t.created_by == "alice" for t in alice_tasks)
    everyone = await task_service.list_tasks(db_session, created_by=None)
    assert len(everyone) >= 2  # admin view sees both


async def test_lifecycle_transitions_and_terminal_idempotency(db_session: AsyncSession) -> None:
    task = await task_service.create_task(db_session, kind=TaskKind.DRIFT_RUN, created_by="x")

    await task_service.mark_running(db_session, task.id)
    await db_session.refresh(task)
    assert task.status == TaskStatus.RUNNING and task.started_at is not None

    await task_service.set_progress(db_session, task.id, 50)
    await db_session.refresh(task)
    assert task.progress == 50

    await task_service.mark_succeeded(db_session, task.id, {"ok": True})
    await db_session.refresh(task)
    assert task.status == TaskStatus.SUCCEEDED
    assert task.progress == 100 and task.result == {"ok": True} and task.finished_at is not None

    # Terminal state is sticky — a late failure does not move it.
    await task_service.mark_failed(db_session, task.id, "too late")
    await db_session.refresh(task)
    assert task.status == TaskStatus.SUCCEEDED


async def test_worker_daily_summary_job_succeeds(db_session: AsyncSession) -> None:
    task = await task_service.create_task(db_session, kind=TaskKind.DAILY_SUMMARY, created_by="x")
    await jobs.run_daily_summary(db_session, task.id)
    await db_session.refresh(task)
    assert task.status == TaskStatus.SUCCEEDED
    assert "report_id" in (task.result or {})


async def test_worker_detection_job_fails_without_model(db_session: AsyncSession) -> None:
    task = await task_service.create_task(
        db_session, kind=TaskKind.DETECTION_RUN, params={"limit": 10}, created_by="x"
    )
    await jobs.run_detection(db_session, task.id)
    await db_session.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert "model" in (task.error or "").lower()


async def test_worker_retention_cleanup_succeeds(db_session: AsyncSession) -> None:
    task = await task_service.create_task(
        db_session, kind=TaskKind.RETENTION_CLEANUP, params={"days": 1}, created_by="x"
    )
    await jobs.run_retention_cleanup(db_session, task.id)
    await db_session.refresh(task)
    assert task.status == TaskStatus.SUCCEEDED
    result = task.result or {}
    assert "retention" in result and "tasks" in result
    assert result["tasks"]["matched"] >= 0
