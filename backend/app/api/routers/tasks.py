"""Background-task API.

    GET  /api/v1/tasks                 — list tasks (own; ADMIN sees all)
    GET  /api/v1/tasks/{id}            — one task (owner or ADMIN)
    POST /api/v1/tasks/detection-run   — enqueue a detection batch (ANALYST+)
    POST /api/v1/tasks/drift-run       — enqueue a drift check (ANALYST+)
    POST /api/v1/tasks/daily-summary   — enqueue the daily summary (ANALYST+)
    POST /api/v1/tasks/report/{alert}  — enqueue a per-alert report (ANALYST+)
    POST /api/v1/tasks/retention-cleanup — housekeeping (ADMIN)
    POST /api/v1/tasks/retrain          — retrain the model (ADMIN, gated)

POSTs return the created task (with its id) immediately — the work runs on the
arq worker. The router is mounted behind method-based RBAC (reads VIEWER+,
mutations ANALYST+) and a per-user "tasks" rate limit guards job spam.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import ActiveUser, SessionDep, rate_limit, require_admin
from app.api.pagination import set_total_count
from app.core.config import get_settings
from app.core.errors import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.models.enums import Role, TaskKind, TaskStatus
from app.schemas.task import (
    DetectionRunTaskRequest,
    DriftRunTaskRequest,
    RetentionCleanupTaskRequest,
    RetrainTaskRequest,
    TaskListOut,
    TaskOut,
)
from app.services import task_service

router = APIRouter(prefix="/tasks")
logger = get_logger(__name__)

_create_limit = Depends(rate_limit("tasks"))


async def _require_retrain_enabled() -> None:
    """Gate the heavy retrain endpoint. As a dependency it runs before the DB
    session is resolved, so a disabled deploy returns 400 without touching the DB."""
    if not get_settings().ml_retrain_enabled:
        raise BadRequestError(
            "ML retrain is disabled. Set SENTINEL_ML_RETRAIN_ENABLED=true to enable it."
        )


@router.get("")
async def list_tasks(
    session: SessionDep,
    response: Response,
    user: ActiveUser,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    kind: TaskKind | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TaskListOut:
    # Non-admins only see their own tasks.
    owner = None if user.role == Role.ADMIN else user.username
    set_total_count(
        response,
        await task_service.count_tasks(session, created_by=owner, status=status_filter, kind=kind),
    )
    tasks = await task_service.list_tasks(
        session, created_by=owner, status=status_filter, kind=kind, limit=limit, offset=offset
    )
    return TaskListOut(items=[TaskOut.model_validate(t) for t in tasks])


@router.get("/{task_id}")
async def get_task(session: SessionDep, task_id: str, user: ActiveUser) -> TaskOut:
    task = await task_service.get_task(session, task_id)
    # 404 (not 403) for someone else's task — don't leak existence of task ids.
    if task is None or (task.created_by != user.username and user.role != Role.ADMIN):
        raise NotFoundError(f"Task '{task_id}' not found.")
    return TaskOut.model_validate(task)


@router.post("/detection-run", status_code=status.HTTP_201_CREATED, dependencies=[_create_limit])
async def enqueue_detection_run(
    session: SessionDep, user: ActiveUser, request: DetectionRunTaskRequest | None = None
) -> TaskOut:
    req = request or DetectionRunTaskRequest()
    task = await task_service.create_task(
        session,
        kind=TaskKind.DETECTION_RUN,
        params={"limit": req.limit},
        created_by=user.username,
    )
    return TaskOut.model_validate(task)


@router.post("/drift-run", status_code=status.HTTP_201_CREATED, dependencies=[_create_limit])
async def enqueue_drift_run(
    session: SessionDep, user: ActiveUser, request: DriftRunTaskRequest | None = None
) -> TaskOut:
    req = request or DriftRunTaskRequest()
    task = await task_service.create_task(
        session,
        kind=TaskKind.DRIFT_RUN,
        params={"window_hours": req.window_hours},
        created_by=user.username,
    )
    return TaskOut.model_validate(task)


@router.post("/daily-summary", status_code=status.HTTP_201_CREATED, dependencies=[_create_limit])
async def enqueue_daily_summary(session: SessionDep, user: ActiveUser) -> TaskOut:
    task = await task_service.create_task(
        session, kind=TaskKind.DAILY_SUMMARY, params={}, created_by=user.username
    )
    return TaskOut.model_validate(task)


@router.post(
    "/report/{alert_id}", status_code=status.HTTP_201_CREATED, dependencies=[_create_limit]
)
async def enqueue_alert_report(session: SessionDep, alert_id: int, user: ActiveUser) -> TaskOut:
    if alert_id < 1:
        raise BadRequestError("alert_id must be positive.")
    task = await task_service.create_task(
        session,
        kind=TaskKind.REPORT_ALERT,
        params={"alert_id": alert_id},
        created_by=user.username,
    )
    return TaskOut.model_validate(task)


@router.post(
    "/retention-cleanup",
    status_code=status.HTTP_201_CREATED,
    dependencies=[_create_limit, Depends(require_admin)],
)
async def enqueue_retention_cleanup(
    session: SessionDep, user: ActiveUser, request: RetentionCleanupTaskRequest | None = None
) -> TaskOut:
    req = request or RetentionCleanupTaskRequest(days=get_settings().retention_days)
    task = await task_service.create_task(
        session,
        kind=TaskKind.RETENTION_CLEANUP,
        params={"days": req.days, "dry_run": req.dry_run},
        created_by=user.username,
    )
    return TaskOut.model_validate(task)


@router.post(
    "/retrain",
    status_code=status.HTTP_201_CREATED,
    dependencies=[_create_limit, Depends(require_admin), Depends(_require_retrain_enabled)],
)
async def enqueue_retrain(
    session: SessionDep, user: ActiveUser, request: RetrainTaskRequest | None = None
) -> TaskOut:
    req = request or RetrainTaskRequest()
    task = await task_service.create_task(
        session,
        kind=TaskKind.ML_RETRAIN,
        params={"synthetic": req.synthetic},
        created_by=user.username,
    )
    return TaskOut.model_validate(task)
