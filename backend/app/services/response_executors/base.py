"""Executor interface, result types, and safety helpers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import ip_address, ip_network
from typing import TYPE_CHECKING, Any

from app.core.errors import AppError
from app.models.enums import ResponseActionType, RollbackStatus

if TYPE_CHECKING:
    from app.models import Alert, ResponseAction


class ExecutorError(AppError):
    """Raised when an action cannot be safely executed (bad target, cap, etc.)."""

    code = "executor_error"
    status_code = 400


# Action types that change real network/host state (vs informational ones).
NETWORK_ACTIONS = frozenset(
    {
        ResponseActionType.BLOCK_IP,
        ResponseActionType.RATE_LIMIT,
        ResponseActionType.ISOLATE_HOST,
    }
)


@dataclass
class ExecutionResult:
    executor_name: str
    simulated: bool
    external_execution_id: str | None = None
    expires_at: datetime | None = None
    rollback_status: RollbackStatus = RollbackStatus.NOT_REQUIRED
    rollback_payload: dict[str, Any] | None = None


@dataclass
class RollbackResult:
    rolled_back: bool
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def network_target_ip(action: ResponseAction) -> str | None:
    """The IP a network action would affect (from the rule-built payload)."""
    payload = action.payload or {}
    target = payload.get("target_ip")
    return str(target) if target else None


def parse_duration_minutes(value: Any) -> int | None:
    """Parse a duration like ``"24h"``, ``"90m"``, ``"3600s"`` → minutes.

    Returns None when there's no parseable duration (e.g. rate-limit payloads).
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    m = re.fullmatch(r"(\d+)\s*([smhd]?)", text)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2) or "m"
    factor = {"s": 1 / 60, "m": 1, "h": 60, "d": 1440}[unit]
    return max(1, round(n * factor))


def validate_in_cidrs(ip: str | None, allowed_cidrs: list[str]) -> str:
    """Return the IP if it parses and falls within an allowed CIDR; else raise."""
    if not ip:
        raise ExecutorError("Action has no target IP to act on.")
    try:
        addr = ip_address(ip)
    except ValueError as exc:
        raise ExecutorError(f"Invalid target IP: {ip!r}.") from exc
    for raw in allowed_cidrs:
        net = ip_network(raw.strip(), strict=False)
        if addr.version == net.version and addr in net:
            return str(addr)
    raise ExecutorError(
        f"Target {ip} is not within the configured lab CIDRs — refusing.",
        details={"target": ip, "allowed_cidrs": allowed_cidrs},
    )


class ResponseExecutor(ABC):
    name: str
    simulated: bool

    @abstractmethod
    def validate(self, action: ResponseAction, alert: Alert) -> None:
        """Raise ExecutorError if this action cannot be safely executed."""

    @abstractmethod
    async def execute(self, action: ResponseAction, alert: Alert) -> ExecutionResult: ...

    @abstractmethod
    async def rollback(self, action: ResponseAction, alert: Alert) -> RollbackResult: ...
