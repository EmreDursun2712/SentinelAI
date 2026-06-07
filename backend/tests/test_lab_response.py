"""Lab-only real-response framework tests.

Covers the safety crux: default stays simulated, LAB is impossible unless fully
configured, out-of-scope targets are rejected, lab network actions require
approval, and rollback works (via MockLabExecutor). The pure/executor pieces are
DB-free; the API surface is tested with the service stubbed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import db_session
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import create_access_token
from app.models import ResponseAction
from app.models.enums import (
    ExecutionMode,
    ResponseActionType,
    Role,
    RollbackStatus,
)
from app.services.response_executors import (
    MockLabExecutor,
    SimulatedExecutor,
    get_executor,
)
from app.services.response_executors.base import (
    ExecutorError,
    parse_duration_minutes,
    validate_in_cidrs,
)
from app.services.response_service import _decide_execution_mode, rollback_action


def _simulated_settings(**over) -> Settings:
    base = dict(response_enabled=False, response_mode="simulated", response_executor="simulated")
    base.update(over)
    return Settings(**base)


def _lab_settings(**over) -> Settings:
    base = dict(
        response_enabled=True,
        response_mode="lab",
        response_executor="mock_lab",
        response_allowed_cidrs="10.0.0.0/8,192.168.0.0/16",
        response_max_block_minutes=60,
    )
    base.update(over)
    return Settings(**base)


def _action(action_type: ResponseActionType, **payload) -> ResponseAction:
    a = ResponseAction(action_type=action_type, payload=payload)
    a.id = 1
    return a


# ---------------------------------------------------------------------------
# Pure helpers.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "minutes"),
    [("24h", 1440), ("6h", 360), ("90m", 90), ("3600s", 60), ("1d", 1440), ("bad", None)],
)
def test_parse_duration_minutes(spec: str, minutes: int | None) -> None:
    assert parse_duration_minutes(spec) == minutes


def test_validate_in_cidrs() -> None:
    cidrs = ["10.0.0.0/8"]
    assert validate_in_cidrs("10.1.2.3", cidrs) == "10.1.2.3"
    with pytest.raises(ExecutorError):
        validate_in_cidrs("8.8.8.8", cidrs)
    with pytest.raises(ExecutorError):
        validate_in_cidrs("not-an-ip", cidrs)
    with pytest.raises(ExecutorError):
        validate_in_cidrs("10.0.0.1", [])  # no cidrs → reject


# ---------------------------------------------------------------------------
# lab_response_active + mode decision (the default-simulated guarantee).
# ---------------------------------------------------------------------------


def test_lab_inactive_by_default() -> None:
    assert _simulated_settings().lab_response_active is False
    # Even enabled but missing pieces → inactive.
    assert (
        _simulated_settings(response_enabled=True, response_mode="lab").lab_response_active is False
    )
    assert _lab_settings(response_allowed_cidrs="").lab_response_active is False
    assert _lab_settings(response_executor="simulated").lab_response_active is False
    assert _lab_settings().lab_response_active is True


def test_decide_mode_defaults_to_simulated() -> None:
    s = _simulated_settings()
    mode, simulated = _decide_execution_mode(ResponseActionType.BLOCK_IP, "10.0.0.5", s)
    assert mode == ExecutionMode.SIMULATED
    assert simulated is True


def test_decide_mode_lab_only_for_in_scope_network_actions() -> None:
    s = _lab_settings()
    # In-scope network action → LAB, real.
    assert _decide_execution_mode(ResponseActionType.BLOCK_IP, "10.0.0.5", s) == (
        ExecutionMode.LAB,
        False,
    )
    # Out-of-scope target → simulated (can't really affect it).
    assert _decide_execution_mode(ResponseActionType.BLOCK_IP, "8.8.8.8", s) == (
        ExecutionMode.SIMULATED,
        True,
    )
    # Informational action → simulated even in scope.
    assert _decide_execution_mode(ResponseActionType.NOTIFY_ANALYST, "10.0.0.5", s) == (
        ExecutionMode.SIMULATED,
        True,
    )


# ---------------------------------------------------------------------------
# get_executor.
# ---------------------------------------------------------------------------


def test_get_executor_simulated() -> None:
    ex = get_executor(_simulated_settings(), ExecutionMode.SIMULATED)
    assert isinstance(ex, SimulatedExecutor)


def test_get_executor_lab_refused_when_inactive() -> None:
    # Asking for a LAB executor while lab is not active is refused outright.
    with pytest.raises(AppError):
        get_executor(_simulated_settings(), ExecutionMode.LAB)


def test_get_executor_lab_mock_when_active() -> None:
    ex = get_executor(_lab_settings(), ExecutionMode.LAB)
    assert isinstance(ex, MockLabExecutor)


# ---------------------------------------------------------------------------
# Executors.
# ---------------------------------------------------------------------------


async def test_simulated_executor_never_real() -> None:
    ex = SimulatedExecutor()
    result = await ex.execute(_action(ResponseActionType.BLOCK_IP, target_ip="10.0.0.5"), None)
    assert result.simulated is True
    assert result.rollback_status == RollbackStatus.NOT_REQUIRED
    assert result.external_execution_id is None


async def test_mock_lab_rejects_out_of_scope_target() -> None:
    ex = MockLabExecutor(allowed_cidrs=["10.0.0.0/8"], max_block_minutes=60)
    action = _action(ResponseActionType.BLOCK_IP, target_ip="8.8.8.8", duration="1h")
    with pytest.raises(ExecutorError):
        ex.validate(action, None)
    with pytest.raises(ExecutorError):
        await ex.execute(action, None)


async def test_mock_lab_executes_and_caps_duration() -> None:
    ex = MockLabExecutor(allowed_cidrs=["10.0.0.0/8"], max_block_minutes=60)
    action = _action(ResponseActionType.BLOCK_IP, target_ip="10.0.0.5", duration="24h")
    result = await ex.execute(action, None)
    assert result.simulated is False
    assert result.executor_name == "mock_lab"
    assert result.external_execution_id and result.external_execution_id.startswith("mock-")
    assert result.rollback_status == RollbackStatus.AVAILABLE
    assert result.rollback_payload["applied_minutes"] == 60  # capped from 1440
    assert result.expires_at is not None


async def test_mock_lab_informational_action_has_no_rollback() -> None:
    ex = MockLabExecutor(allowed_cidrs=["10.0.0.0/8"], max_block_minutes=60)
    action = _action(ResponseActionType.NOTIFY_ANALYST)
    result = await ex.execute(action, None)
    assert result.rollback_status == RollbackStatus.NOT_REQUIRED


async def test_mock_lab_rollback() -> None:
    ex = MockLabExecutor(allowed_cidrs=["10.0.0.0/8"], max_block_minutes=60)
    action = _action(ResponseActionType.BLOCK_IP, target_ip="10.0.0.5")
    action.external_execution_id = "mock-abc"
    result = await ex.rollback(action, None)
    assert result.rolled_back is True


# ---------------------------------------------------------------------------
# rollback_action guard.
# ---------------------------------------------------------------------------


async def test_rollback_action_rejects_when_not_available() -> None:
    action = SimpleNamespace(id=1, rollback_status=RollbackStatus.NOT_REQUIRED, alert_id=1)
    with pytest.raises(AppError):
        await rollback_action(object(), action)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# API surface (auth + serialization; service stubbed).
# ---------------------------------------------------------------------------


async def _dummy_session() -> AsyncIterator[None]:
    yield None


def _headers(role: Role) -> dict[str, str]:
    token, _ = create_access_token("resp-user", {"role": role.value})
    return {"Authorization": f"Bearer {token}"}


async def test_rollback_requires_auth(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/response/1/rollback")).status_code == 401


async def test_rollback_forbidden_for_viewer(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/response/1/rollback", headers=_headers(Role.VIEWER))
    assert resp.status_code == 403


async def test_rollback_analyst_happy_path(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from app.api.routers import response as response_router
    from app.models.enums import ResponseStatus

    now = datetime.now(UTC)
    rolled = ResponseAction(
        action_type=ResponseActionType.BLOCK_IP,
        execution_mode=ExecutionMode.LAB,
        simulated=False,
        status=ResponseStatus.EXECUTED,
        executed=True,
        approval_required=True,
        rollback_status=RollbackStatus.ROLLED_BACK,
        payload={"target_ip": "10.0.0.5"},
    )
    # Transient ORM instance — set the non-nullable fields the DTO requires.
    rolled.id = 5
    rolled.alert_id = 9
    rolled.decision_id = None
    rolled.created_at = now
    rolled.updated_at = now

    class _Sess:
        async def get(self, model, ident):
            return rolled

    async def _sess_override() -> AsyncIterator[_Sess]:
        yield _Sess()

    async def fake_rollback(session, action, **kw):
        return rolled

    app.dependency_overrides[db_session] = _sess_override
    monkeypatch.setattr(response_router, "svc_rollback", fake_rollback)

    resp = await client.post("/api/v1/response/5/rollback", headers=_headers(Role.ANALYST))
    assert resp.status_code == 200
    body = resp.json()
    assert body["rollback_status"] == "ROLLED_BACK"
    assert body["execution_mode"] == "LAB"
    assert body["simulated"] is False
    app.dependency_overrides.clear()
