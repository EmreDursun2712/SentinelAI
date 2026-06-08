"""Task API + queue unit tests (DB-free)."""

from __future__ import annotations

from httpx import AsyncClient

from app.core.queue import NullTaskQueue
from app.core.security import create_access_token
from app.models.enums import Role, TaskKind
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
