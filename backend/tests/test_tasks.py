"""Task API + queue unit tests (DB-free)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import db_session
from app.core.queue import NullTaskQueue
from app.core.security import create_access_token
from app.models.enums import Role, TaskKind
from app.services import task_service
from app.services.task_service import KIND_FUNCTION


def _headers(role: Role, username: str = "u") -> dict[str, str]:
    token, _ = create_access_token(username, {"role": role.value})
    return {"Authorization": f"Bearer {token}"}


def test_kind_function_maps_every_task_kind() -> None:
    assert set(KIND_FUNCTION) == set(TaskKind)


async def test_null_queue_is_a_noop() -> None:
    queue = NullTaskQueue()
    assert await queue.enqueue("detection_run_task", "id-1") is None
    assert await queue.ping() is False
    await queue.aclose()  # must not raise


async def test_list_tasks_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/tasks")).status_code == 401


async def test_get_task_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/tasks/some-id")).status_code == 401


async def test_enqueue_detection_forbidden_for_viewer(client: AsyncClient) -> None:
    # POST is a mutation → ANALYST+; VIEWER is rejected before the handler/DB.
    resp = await client.post("/api/v1/tasks/detection-run", headers=_headers(Role.VIEWER))
    assert resp.status_code == 403


async def test_retention_cleanup_is_admin_only(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/tasks/retention-cleanup", headers=_headers(Role.ANALYST))
    assert resp.status_code == 403


async def test_retrain_disabled_returns_400(client: AsyncClient) -> None:
    # ADMIN passes RBAC; retrain is disabled by default → 400 before any DB work.
    resp = await client.post("/api/v1/tasks/retrain", headers=_headers(Role.ADMIN, "admin"))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


async def test_list_tasks_sets_total_count_header(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _dummy_session() -> AsyncIterator[None]:
        yield None

    app.dependency_overrides[db_session] = _dummy_session

    async def fake_list(session, **kwargs):
        return []

    async def fake_count(session, **kwargs):
        return 7

    monkeypatch.setattr(task_service, "list_tasks", fake_list)
    monkeypatch.setattr(task_service, "count_tasks", fake_count)

    resp = await client.get("/api/v1/tasks", headers=_headers(Role.ANALYST))
    assert resp.status_code == 200
    assert resp.headers["x-total-count"] == "7"
