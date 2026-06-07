"""MockLabExecutor — exercises the full LAB path without touching anything.

It runs every guardrail a real lab executor does (CIDR allowlist, duration cap,
rollback bookkeeping) and records an ``external_execution_id`` + ``expires_at``,
but performs no real action. Used for tests and safe demos of LAB mode.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.models.enums import RollbackStatus
from app.services.response_executors.base import (
    NETWORK_ACTIONS,
    ExecutionResult,
    ResponseExecutor,
    RollbackResult,
    network_target_ip,
    parse_duration_minutes,
    validate_in_cidrs,
)

if TYPE_CHECKING:
    from app.models import Alert, ResponseAction

logger = get_logger(__name__)


class MockLabExecutor(ResponseExecutor):
    name = "mock_lab"
    simulated = False  # represents a real LAB action (mock effect, fully audited)

    def __init__(self, *, allowed_cidrs: list[str], max_block_minutes: int) -> None:
        self._cidrs = allowed_cidrs
        self._cap = max_block_minutes

    def validate(self, action: ResponseAction, alert: Alert) -> None:
        if action.action_type in NETWORK_ACTIONS:
            validate_in_cidrs(network_target_ip(action), self._cidrs)

    def _applied_minutes(self, action: ResponseAction) -> int | None:
        requested = parse_duration_minutes((action.payload or {}).get("duration"))
        if requested is None:
            return None
        return min(requested, self._cap)  # cap enforced

    async def execute(self, action: ResponseAction, alert: Alert) -> ExecutionResult:
        self.validate(action, alert)
        target = network_target_ip(action)
        is_network = action.action_type in NETWORK_ACTIONS
        applied = self._applied_minutes(action)
        exec_id = f"mock-{uuid.uuid4().hex[:12]}"
        expires_at = (
            datetime.now(UTC) + timedelta(minutes=applied)
            if applied is not None
            else None
        )
        logger.info(
            "lab.mock_execute",
            action_id=action.id,
            action_type=action.action_type.value,
            target=target,
            applied_minutes=applied,
            external_execution_id=exec_id,
        )
        return ExecutionResult(
            executor_name=self.name,
            simulated=False,
            external_execution_id=exec_id,
            expires_at=expires_at,
            rollback_status=(
                RollbackStatus.AVAILABLE if is_network else RollbackStatus.NOT_REQUIRED
            ),
            rollback_payload=(
                {"target_ip": target, "applied_minutes": applied, "executor": self.name}
                if is_network
                else None
            ),
        )

    async def rollback(self, action: ResponseAction, alert: Alert) -> RollbackResult:
        logger.info(
            "lab.mock_rollback",
            action_id=action.id,
            external_execution_id=action.external_execution_id,
        )
        return RollbackResult(rolled_back=True, detail={"executor": self.name})
