"""NftablesLabExecutor — real, isolated-lab firewall effect via nftables.

⚠️ Only for a dedicated, authorized lab host. It adds/removes the validated
target IP to a pre-created nftables set, so a rollback is a single delete. It is
safe-by-construction:

* the target IP is parsed with ``ipaddress`` and re-stringified before use — the
  value passed to ``nft`` is never attacker-controlled text;
* commands run via ``create_subprocess_exec`` (argv list, **no shell**), so there
  is no command-injection surface;
* it only ever operates on the allowlisted lab CIDRs and the configured set.

Prerequisites on the lab host (created out-of-band by the operator), e.g.:

    nft add table inet sentinelai
    nft add set inet sentinelai lab_block { type ipv4_addr\\; flags timeout\\; }
    nft add chain inet sentinelai input { type filter hook input priority 0\\; }
    nft add rule inet sentinelai input ip saddr @lab_block drop

This executor is never selected unless ``SENTINEL_RESPONSE_EXECUTOR=nftables_lab``
and lab response is fully enabled.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.models.enums import RollbackStatus
from app.services.response_executors.base import (
    NETWORK_ACTIONS,
    ExecutionResult,
    ExecutorError,
    ResponseExecutor,
    RollbackResult,
    network_target_ip,
    parse_duration_minutes,
    validate_in_cidrs,
)

if TYPE_CHECKING:
    from app.models import Alert, ResponseAction

logger = get_logger(__name__)

_TABLE = "inet sentinelai"
_SET = "lab_block"


class NftablesLabExecutor(ResponseExecutor):
    name = "nftables_lab"
    simulated = False

    def __init__(self, *, allowed_cidrs: list[str], max_block_minutes: int) -> None:
        self._cidrs = allowed_cidrs
        self._cap = max_block_minutes

    def validate(self, action: ResponseAction, alert: Alert) -> None:
        if action.action_type in NETWORK_ACTIONS:
            validate_in_cidrs(network_target_ip(action), self._cidrs)

    async def _nft(self, *args: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "nft",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise ExecutorError(
                "nftables command failed.",
                details={"args": list(args), "stderr": stderr.decode()[:300]},
            )

    async def execute(self, action: ResponseAction, alert: Alert) -> ExecutionResult:
        # Re-validate → returns a clean, canonical IP string (never raw input).
        target = validate_in_cidrs(network_target_ip(action), self._cidrs)
        requested = parse_duration_minutes((action.payload or {}).get("duration"))
        minutes = min(requested or self._cap, self._cap)

        # `nft add element ... { <ip> timeout <n>m }` — argv list, no shell.
        element = f"{{ {target} timeout {minutes}m }}"
        await self._nft("add", "element", *_TABLE.split(), _SET, element)
        logger.info("lab.nft_block", action_id=action.id, target=target, minutes=minutes)

        return ExecutionResult(
            executor_name=self.name,
            simulated=False,
            external_execution_id=f"nft:{_SET}:{target}",
            rollback_status=RollbackStatus.AVAILABLE,
            rollback_payload={"target_ip": target, "set": _SET, "applied_minutes": minutes},
        )

    async def rollback(self, action: ResponseAction, alert: Alert) -> RollbackResult:
        payload = action.rollback_payload or {}
        target = payload.get("target_ip")
        if not target:
            return RollbackResult(rolled_back=False, error="no rollback target recorded")
        try:
            await self._nft("delete", "element", *_TABLE.split(), _SET, f"{{ {target} }}")
        except ExecutorError as exc:
            return RollbackResult(rolled_back=False, error=str(exc.message))
        return RollbackResult(rolled_back=True, detail={"target_ip": target})
