"""Response executors — how a ResponseAction is carried out.

The default ``SimulatedExecutor`` never touches a real system. Lab executors
(``MockLabExecutor`` for tests/demo, ``NftablesLabExecutor`` for an isolated lab
host) perform a controlled, allowlisted, reversible effect — and only when
``settings.lab_response_active`` is true.
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import AppError
from app.models.enums import ExecutionMode
from app.services.response_executors.base import (
    ExecutionResult,
    ExecutorError,
    ResponseExecutor,
    RollbackResult,
    network_target_ip,
)
from app.services.response_executors.mock_lab import MockLabExecutor
from app.services.response_executors.nftables_lab import NftablesLabExecutor
from app.services.response_executors.simulated import SimulatedExecutor

__all__ = [
    "ExecutionResult",
    "ExecutorError",
    "MockLabExecutor",
    "NftablesLabExecutor",
    "ResponseExecutor",
    "RollbackResult",
    "SimulatedExecutor",
    "get_executor",
    "network_target_ip",
]


def get_executor(settings: Settings, mode: ExecutionMode) -> ResponseExecutor:
    """Pick the executor for an action's ``mode``.

    SIMULATED → the no-op simulated executor. LAB → the configured lab executor,
    but only if lab response is fully + safely enabled; otherwise we refuse
    (never silently downgrade a LAB action to a real effect or vice-versa).
    """
    if mode == ExecutionMode.SIMULATED:
        return SimulatedExecutor()

    if not settings.lab_response_active:
        raise AppError(
            "LAB response is not enabled or is misconfigured; refusing to execute a LAB action.",
            details={
                "response_enabled": settings.response_enabled,
                "response_mode": settings.response_mode,
                "response_executor": settings.response_executor,
                "allowed_cidrs": settings.response_allowed_cidrs_list,
            },
        )

    cidrs = settings.response_allowed_cidrs_list
    cap = settings.response_max_block_minutes
    executor = settings.response_executor.strip().lower()
    if executor == "mock_lab":
        return MockLabExecutor(allowed_cidrs=cidrs, max_block_minutes=cap)
    if executor == "nftables_lab":
        return NftablesLabExecutor(allowed_cidrs=cidrs, max_block_minutes=cap)
    raise AppError(f"Unknown lab executor {executor!r}.")
