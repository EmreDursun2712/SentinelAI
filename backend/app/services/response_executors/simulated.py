"""SimulatedExecutor — the default. Never contacts a real system."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.enums import RollbackStatus
from app.services.response_executors.base import (
    ExecutionResult,
    ResponseExecutor,
    RollbackResult,
)

if TYPE_CHECKING:
    from app.models import Alert, ResponseAction


class SimulatedExecutor(ResponseExecutor):
    name = "simulated"
    simulated = True

    def validate(self, action: ResponseAction, alert: Alert) -> None:
        return None  # nothing can go wrong — nothing happens

    async def execute(self, action: ResponseAction, alert: Alert) -> ExecutionResult:
        # Records intent only; no external effect, nothing to roll back.
        return ExecutionResult(
            executor_name=self.name,
            simulated=True,
            rollback_status=RollbackStatus.NOT_REQUIRED,
        )

    async def rollback(self, action: ResponseAction, alert: Alert) -> RollbackResult:
        return RollbackResult(rolled_back=True, detail={"note": "simulated; no-op"})
