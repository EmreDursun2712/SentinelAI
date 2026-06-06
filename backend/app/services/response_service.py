"""Response Agent service.

Two entry points:

* ``recommend_for_alert`` — generate + persist recommendations for an alert.
  Auto-execute simulated effects inline; analyst-approval actions stay
  PENDING. Updates alert.status appropriately.
* ``approve_action`` / ``reject_action`` — analyst feedback paths.

All ``response_actions`` rows are inserted with ``simulated=TRUE`` (a DB-level
CHECK constraint enforces this — see migration 0001).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from ipaddress import IPv4Address, IPv6Address
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.events import EventType, publish_event
from app.core.logging import get_logger
from app.models import AgentDecision, Alert, ResponseAction
from app.models.enums import (
    AgentName,
    AlertDisposition,
    AlertStatus,
    ResponseActionType,
    ResponseStatus,
)
from app.services.response_rules import recommend_actions

logger = get_logger(__name__)


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

    persisted: list[ResponseAction] = []
    has_pending = False
    has_auto_executed = False

    for rec in recommendations:
        action = ResponseAction(
            alert_id=alert.id,
            action_type=rec.action_type,
            simulated=True,  # DB CHECK enforces this — explicit for clarity
            status=ResponseStatus.PENDING,
            executed=False,
            approval_required=not rec.auto_execute,
            payload=_jsonable({"rationale": rec.rationale, **rec.payload}),
        )
        session.add(action)
        await session.flush()
        persisted.append(action)

        if rec.auto_execute:
            _simulate_execute(action, alert)
            has_auto_executed = True
        else:
            has_pending = True

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
            f"ResponseAction {action.id} is not pending "
            f"(status={action.status.value}).",
            details={"action_id": action.id, "status": action.status.value},
        )

    alert = await session.get(Alert, action.alert_id)
    if alert is None:
        raise AppError(f"Alert {action.alert_id} not found for action {action.id}.")

    action.approved_by = analyst_id
    _simulate_execute(action, alert)

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
            f"ResponseAction {action.id} is not pending "
            f"(status={action.status.value}).",
            details={"action_id": action.id, "status": action.status.value},
        )
    if not reason or not reason.strip():
        raise AppError("Rejection reason is required.")

    action.status = ResponseStatus.REJECTED
    action.rejection_reason = reason.strip()
    action.approved_by = analyst_id

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


def _simulate_execute(action: ResponseAction, alert: Alert) -> None:
    """Mark the action executed and apply side-effects on the alert.

    All "execution" here is simulated — no external system is contacted; we
    just stamp executed=True, fill executed_at, and update alert disposition
    when the action type calls for it.
    """
    now = datetime.now(UTC)
    action.status = ResponseStatus.EXECUTED
    action.executed = True
    action.executed_at = now

    target_disposition = _DISPOSITION_SIDE_EFFECTS.get(action.action_type)
    if target_disposition is not None:
        # ESCALATE only escalates OPEN alerts; if the analyst already moved
        # the disposition, respect their choice.
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
