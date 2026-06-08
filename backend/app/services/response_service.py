"""Response Agent service.

Two entry points:

* ``recommend_for_alert`` — generate + persist recommendations for an alert.
  Auto-execute simulated effects inline; analyst-approval actions stay
  PENDING. Updates alert.status appropriately.
* ``approve_action`` / ``reject_action`` / ``rollback_action`` — analyst paths.

Execution is routed through a :class:`ResponseExecutor` chosen by the action's
``execution_mode``. Rows are ``simulated=TRUE`` by default; a non-simulated (real)
row is only possible in ``LAB`` mode, which the DB CHECK
``ck_response_actions_simulated_unless_lab`` enforces. LAB mode itself is gated by
config + analyst approval — see ``app.services.response_executors``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.events import EventType, publish_event
from app.core.logging import get_logger
from app.core.metrics import RESPONSE_ACTIONS
from app.models import AgentDecision, Alert, ResponseAction
from app.models.enums import (
    AgentName,
    AlertDisposition,
    AlertStatus,
    ExecutionMode,
    ResponseActionType,
    ResponseStatus,
    RollbackStatus,
)
from app.services.response_executors import (
    get_executor,
)
from app.services.response_executors.base import NETWORK_ACTIONS
from app.services.response_rules import recommend_actions

logger = get_logger(__name__)


def _target_in_lab_cidrs(ip: str | None, settings: Settings) -> bool:
    """Non-raising scope check used when deciding an action's execution mode."""
    if not ip:
        return False
    try:
        addr = ip_address(ip)
    except ValueError:
        return False
    for raw in settings.response_allowed_cidrs_list:
        net = ip_network(raw.strip(), strict=False)
        if addr.version == net.version and addr in net:
            return True
    return False


def _decide_execution_mode(
    action_type: ResponseActionType, target_ip: str | None, settings: Settings
) -> tuple[ExecutionMode, bool]:
    """Return ``(execution_mode, simulated)`` for a new action.

    A network action becomes a real ``LAB`` action only when lab response is
    fully enabled AND its target is inside an allowed lab CIDR. Everything else
    — informational actions, out-of-scope targets, default config — stays
    SIMULATED (simulated=True), so real effects are impossible by default.
    """
    if (
        settings.lab_response_active
        and action_type in NETWORK_ACTIONS
        and _target_in_lab_cidrs(target_ip, settings)
    ):
        return ExecutionMode.LAB, False
    return ExecutionMode.SIMULATED, True


# Side-effect-bearing action types — used both by inline auto-execute and by
# the analyst /approve path so behavior stays consistent.
_DISPOSITION_SIDE_EFFECTS: dict[ResponseActionType, AlertDisposition] = {
    ResponseActionType.SUPPRESS_ALERT: AlertDisposition.FALSE_POSITIVE,
    ResponseActionType.ESCALATE: AlertDisposition.UNDER_REVIEW,
}


def _jsonable(value: Any) -> Any:
    """Normalize rule payload values before storing them in JSONB columns."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, IPv4Address | IPv6Address):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Generate + persist recommendations.
# ---------------------------------------------------------------------------


async def recommend_for_alert(
    session: AsyncSession,
    alert: Alert,
    *,
    commit: bool = True,
) -> list[ResponseAction]:
    """Run the rule engine, persist actions, auto-execute the safe ones."""
    recommendations = recommend_actions(alert)
    if not recommendations:
        logger.info("response.no_recommendations", alert_id=alert.id, status=str(alert.status))
        if commit:
            await session.commit()
        return []

    settings = get_settings()
    persisted: list[ResponseAction] = []
    has_pending = False
    has_auto_executed = False

    for rec in recommendations:
        target_ip = rec.payload.get("target_ip")
        mode, simulated = _decide_execution_mode(rec.action_type, target_ip, settings)

        # LAB network actions ALWAYS require analyst approval — they never
        # auto-execute against a real system, even at HIGH/CRITICAL severity.
        is_lab_network = mode == ExecutionMode.LAB and rec.action_type in NETWORK_ACTIONS
        approval_required = True if is_lab_network else (not rec.auto_execute)

        action = ResponseAction(
            alert_id=alert.id,
            action_type=rec.action_type,
            execution_mode=mode,
            simulated=simulated,
            status=ResponseStatus.PENDING,
            executed=False,
            approval_required=approval_required,
            payload=_jsonable({"rationale": rec.rationale, **rec.payload}),
        )
        session.add(action)
        await session.flush()
        persisted.append(action)

        # Auto-execute only safe, non-approval actions. In SIMULATED mode that's
        # the existing behavior; LAB network actions are excluded above.
        if not approval_required and rec.auto_execute:
            await _run_executor(session, action, alert, settings)
            has_auto_executed = True
            RESPONSE_ACTIONS.labels(status="executed", type=action.action_type.value).inc()
        else:
            has_pending = True
            RESPONSE_ACTIONS.labels(status="pending", type=action.action_type.value).inc()

    # Advance alert state only if we're still in the agent workflow.
    alert.responded_at = datetime.now(UTC)
    if alert.status in (AlertStatus.NEW, AlertStatus.TRIAGED):
        if has_pending:
            alert.status = AlertStatus.AWAITING_ANALYST
        elif has_auto_executed:
            alert.status = AlertStatus.AUTO_RESPONDED

    decision = AgentDecision(
        alert_id=alert.id,
        agent=AgentName.RESPONSE,
        decision={
            "n_recommendations": len(recommendations),
            "n_auto_executed": sum(1 for r in recommendations if r.auto_execute),
            "n_awaiting_approval": sum(1 for r in recommendations if not r.auto_execute),
            "action_ids": [a.id for a in persisted],
        },
        reasoning={
            "recommendations": [
                {
                    "action_type": r.action_type.value,
                    "auto_execute": r.auto_execute,
                    "rationale": r.rationale,
                    "payload": _jsonable(r.payload),
                }
                for r in recommendations
            ],
        },
    )
    session.add(decision)

    if commit:
        await session.commit()
        await session.refresh(alert)
        # Refresh so server-side columns (timestamps, defaults) are loaded for
        # serialization — avoids a lazy-load in the async response path.
        for a in persisted:
            await session.refresh(a)

    logger.info(
        "response.recommendations_created",
        alert_id=alert.id,
        n_actions=len(persisted),
        auto=has_auto_executed,
        pending=has_pending,
    )
    # Only broadcast on the committing (endpoint) path. When commit=False the
    # Detection orchestrator already emits alert.responded after its commit.
    if commit:
        n_auto = sum(1 for a in persisted if a.executed)
        n_pending = sum(1 for a in persisted if a.status == ResponseStatus.PENDING)
        if n_auto:
            await publish_event(
                EventType.RESPONSE_ACTION_EXECUTED,
                {"alert_id": alert.id, "count": n_auto},
            )
        if n_pending:
            await publish_event(
                EventType.RESPONSE_ACTION_PENDING,
                {"alert_id": alert.id, "count": n_pending},
            )
    return persisted


# ---------------------------------------------------------------------------
# Analyst approval / rejection.
# ---------------------------------------------------------------------------


async def approve_action(
    session: AsyncSession,
    action: ResponseAction,
    *,
    analyst_id: str | None = None,
    note: str | None = None,
) -> ResponseAction:
    """Simulate-execute a pending action. Auto-loads the alert for side effects."""
    if action.status != ResponseStatus.PENDING:
        raise AppError(
            f"ResponseAction {action.id} is not pending (status={action.status.value}).",
            details={"action_id": action.id, "status": action.status.value},
        )

    alert = await session.get(Alert, action.alert_id)
    if alert is None:
        raise AppError(f"Alert {action.alert_id} not found for action {action.id}.")

    action.approved_by = analyst_id
    # Routes through the executor for this action's mode (SimulatedExecutor for
    # SIMULATED; the configured lab executor for LAB). Validation failures (e.g.
    # target outside the lab CIDRs) raise and leave the action PENDING.
    await _run_executor(session, action, alert, get_settings())
    RESPONSE_ACTIONS.labels(status="executed", type=action.action_type.value).inc()

    _append_analyst_decision(
        session,
        alert_id=alert.id,
        action=action,
        verb="approve",
        analyst_id=analyst_id,
        note=note,
    )

    await _maybe_advance_status(session, alert)

    await session.commit()
    await session.refresh(action)
    await session.refresh(alert)

    await publish_event(
        EventType.RESPONSE_ACTION_EXECUTED,
        {
            "action_id": action.id,
            "alert_id": alert.id,
            "action_type": action.action_type.value,
        },
    )
    # SUPPRESS_ALERT closes the alert as a side effect.
    if alert.status == AlertStatus.CLOSED:
        await publish_event(EventType.ALERT_CLOSED, {"alert_id": alert.id})
    return action


async def reject_action(
    session: AsyncSession,
    action: ResponseAction,
    *,
    reason: str,
    analyst_id: str | None = None,
) -> ResponseAction:
    if action.status != ResponseStatus.PENDING:
        raise AppError(
            f"ResponseAction {action.id} is not pending (status={action.status.value}).",
            details={"action_id": action.id, "status": action.status.value},
        )
    if not reason or not reason.strip():
        raise AppError("Rejection reason is required.")

    action.status = ResponseStatus.REJECTED
    action.rejection_reason = reason.strip()
    action.approved_by = analyst_id
    RESPONSE_ACTIONS.labels(status="rejected", type=action.action_type.value).inc()

    _append_analyst_decision(
        session,
        alert_id=action.alert_id,
        action=action,
        verb="reject",
        analyst_id=analyst_id,
        note=reason.strip(),
    )

    alert = await session.get(Alert, action.alert_id)
    if alert is not None:
        await _maybe_advance_status(session, alert)

    await session.commit()
    await session.refresh(action)

    await publish_event(
        EventType.RESPONSE_ACTION_REJECTED,
        {
            "action_id": action.id,
            "alert_id": action.alert_id,
            "action_type": action.action_type.value,
        },
    )
    return action


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


async def _run_executor(
    session: AsyncSession,
    action: ResponseAction,
    alert: Alert,
    settings: Settings,
) -> None:
    """Execute ``action`` through the executor for its mode; record the result.

    Raises ``ExecutorError`` (→ 400) on a refused/failed execution, leaving the
    action PENDING. Disposition side-effects (suppress/escalate) are applied for
    the relevant action types regardless of executor — they are alert state, not
    a network effect.
    """
    executor = get_executor(settings, action.execution_mode)
    executor.validate(action, alert)  # may raise ExecutorError
    result = await executor.execute(action, alert)

    now = datetime.now(UTC)
    action.status = ResponseStatus.EXECUTED
    action.executed = True
    action.executed_at = now
    action.simulated = result.simulated
    action.executor_name = result.executor_name
    action.external_execution_id = result.external_execution_id
    action.expires_at = result.expires_at
    action.rollback_status = result.rollback_status
    action.rollback_payload = result.rollback_payload
    action.execution_error = None

    _apply_disposition_side_effects(action, alert, now)


def _apply_disposition_side_effects(action: ResponseAction, alert: Alert, now: datetime) -> None:
    target_disposition = _DISPOSITION_SIDE_EFFECTS.get(action.action_type)
    if target_disposition is None:
        return
    # ESCALATE only escalates OPEN alerts; respect an analyst's prior choice.
    if action.action_type == ResponseActionType.ESCALATE:
        if alert.disposition == AlertDisposition.OPEN:
            alert.disposition = AlertDisposition.UNDER_REVIEW
    else:
        alert.disposition = target_disposition

    # SUPPRESS_ALERT also closes the workflow.
    if target_disposition == AlertDisposition.FALSE_POSITIVE:
        alert.status = AlertStatus.CLOSED
        if alert.closed_at is None:
            alert.closed_at = now


async def rollback_action(
    session: AsyncSession,
    action: ResponseAction,
    *,
    analyst_id: str | None = None,
    note: str | None = None,
) -> ResponseAction:
    """Revert an executed LAB action whose effect is still in place."""
    if action.rollback_status != RollbackStatus.AVAILABLE:
        raise AppError(
            f"ResponseAction {action.id} has no rollback available "
            f"(rollback_status={action.rollback_status.value}).",
            details={"action_id": action.id, "rollback_status": action.rollback_status.value},
        )

    alert = await session.get(Alert, action.alert_id)
    executor = get_executor(get_settings(), action.execution_mode)
    result = await executor.rollback(action, alert)
    if result.rolled_back:
        action.rollback_status = RollbackStatus.ROLLED_BACK
        action.execution_error = None
    else:
        action.rollback_status = RollbackStatus.FAILED
        action.execution_error = result.error

    _append_analyst_decision(
        session,
        alert_id=action.alert_id,
        action=action,
        verb="rollback",
        analyst_id=analyst_id,
        note=note or result.error,
    )

    await session.commit()
    await session.refresh(action)

    await publish_event(
        EventType.RESPONSE_ACTION_EXECUTED,
        {
            "action_id": action.id,
            "alert_id": action.alert_id,
            "action_type": action.action_type.value,
            "rollback_status": action.rollback_status.value,
        },
    )
    logger.info(
        "response.rolled_back",
        action_id=action.id,
        status=action.rollback_status.value,
        analyst_id=analyst_id,
    )
    return action


def _append_analyst_decision(
    session: AsyncSession,
    *,
    alert_id: int,
    action: ResponseAction,
    verb: str,
    analyst_id: str | None,
    note: str | None,
) -> None:
    decision = AgentDecision(
        alert_id=alert_id,
        agent=AgentName.ANALYST,
        decision={
            "verb": verb,
            "action_id": action.id,
            "action_type": action.action_type.value,
        },
        reasoning={"analyst_id": analyst_id, "note": (note or "").strip() or None},
    )
    session.add(decision)


async def _maybe_advance_status(session: AsyncSession, alert: Alert) -> None:
    """If no actions remain PENDING, lift alert out of AWAITING_ANALYST."""
    if alert.status != AlertStatus.AWAITING_ANALYST:
        return
    pending = await session.execute(
        select(func.count(ResponseAction.id)).where(
            ResponseAction.alert_id == alert.id,
            ResponseAction.status == ResponseStatus.PENDING,
        )
    )
    if int(pending.scalar_one() or 0) == 0:
        # Everything settled — back to AUTO_RESPONDED so downstream agents
        # (Investigation, Reporting) can pick it up.
        alert.status = AlertStatus.AUTO_RESPONDED


async def list_actions(
    session: AsyncSession,
    *,
    alert_id: int | None = None,
    status: ResponseStatus | None = None,
    action_type: ResponseActionType | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ResponseAction]:
    stmt = select(ResponseAction).order_by(ResponseAction.created_at.desc())
    if alert_id is not None:
        stmt = stmt.where(ResponseAction.alert_id == alert_id)
    if status is not None:
        stmt = stmt.where(ResponseAction.status == status)
    if action_type is not None:
        stmt = stmt.where(ResponseAction.action_type == action_type)
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
