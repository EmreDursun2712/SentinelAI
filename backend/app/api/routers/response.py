"""Response Center API.

Surface:

    GET  /api/v1/response               — list actions (filters: alert_id, status, action_type)
    GET  /api/v1/response/pending       — convenience: status=PENDING
    GET  /api/v1/response/{action_id}   — single action detail
    POST /api/v1/response/recommend/{alert_id}  — generate recommendations for an alert
    POST /api/v1/response/{action_id}/approve   — simulate-execute the action
    POST /api/v1/response/{action_id}/reject    — reject with reason
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import SessionDep, rate_limit
from app.api.pagination import set_total_count
from app.core.errors import NotFoundError
from app.models import Alert, ResponseAction
from app.models.enums import ResponseActionType, ResponseStatus
from app.schemas.response import (
    ApproveRequest,
    RecommendResponse,
    RejectRequest,
    ResponseActionOut,
    RollbackRequest,
)
from app.services.response_service import (
    approve_action as svc_approve,
)
from app.services.response_service import (
    count_actions as svc_count,
)
from app.services.response_service import (
    list_actions as svc_list,
)
from app.services.response_service import (
    recommend_for_alert,
)
from app.services.response_service import (
    reject_action as svc_reject,
)
from app.services.response_service import (
    rollback_action as svc_rollback,
)

router = APIRouter(prefix="/response")


def _to_out(action: ResponseAction) -> ResponseActionOut:
    return ResponseActionOut.model_validate(action)


@router.get("/pending")
async def list_pending_actions(
    session: SessionDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[ResponseActionOut]:
    set_total_count(response, await svc_count(session, status=ResponseStatus.PENDING))
    actions = await svc_list(session, status=ResponseStatus.PENDING, limit=limit, offset=offset)
    return [_to_out(a) for a in actions]


@router.get("")
async def list_response_actions(
    session: SessionDep,
    response: Response,
    alert_id: Annotated[int | None, Query(ge=1)] = None,
    status_filter: Annotated[ResponseStatus | None, Query(alias="status")] = None,
    action_type: Annotated[ResponseActionType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[ResponseActionOut]:
    set_total_count(
        response,
        await svc_count(session, alert_id=alert_id, status=status_filter, action_type=action_type),
    )
    actions = await svc_list(
        session,
        alert_id=alert_id,
        status=status_filter,
        action_type=action_type,
        limit=limit,
        offset=offset,
    )
    return [_to_out(a) for a in actions]


@router.post(
    "/recommend/{alert_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("response"))],
)
async def recommend_for_alert_endpoint(session: SessionDep, alert_id: int) -> RecommendResponse:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise NotFoundError(f"Alert {alert_id} not found.")
    actions = await recommend_for_alert(session, alert, commit=True)
    return RecommendResponse(
        alert_id=alert.id,
        actions=[_to_out(a) for a in actions],
    )


@router.get("/{action_id}")
async def get_response_action(session: SessionDep, action_id: int) -> ResponseActionOut:
    action = await session.get(ResponseAction, action_id)
    if action is None:
        raise NotFoundError(f"ResponseAction {action_id} not found.")
    return _to_out(action)


@router.post(
    "/{action_id}/approve",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("response"))],
)
async def approve_response_action(
    session: SessionDep,
    action_id: int,
    request: ApproveRequest | None = None,
) -> ResponseActionOut:
    action = await session.get(ResponseAction, action_id)
    if action is None:
        raise NotFoundError(f"ResponseAction {action_id} not found.")
    req = request or ApproveRequest()
    updated = await svc_approve(session, action, analyst_id=req.analyst_id, note=req.note)
    return _to_out(updated)


@router.post(
    "/{action_id}/reject",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("response"))],
)
async def reject_response_action(
    session: SessionDep, action_id: int, request: RejectRequest
) -> ResponseActionOut:
    action = await session.get(ResponseAction, action_id)
    if action is None:
        raise NotFoundError(f"ResponseAction {action_id} not found.")
    updated = await svc_reject(
        session, action, reason=request.reason, analyst_id=request.analyst_id
    )
    return _to_out(updated)


@router.post(
    "/{action_id}/rollback",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit("response"))],
)
async def rollback_response_action(
    session: SessionDep,
    action_id: int,
    request: RollbackRequest | None = None,
) -> ResponseActionOut:
    """Revert an executed LAB action whose effect is still in place (ANALYST+)."""
    action = await session.get(ResponseAction, action_id)
    if action is None:
        raise NotFoundError(f"ResponseAction {action_id} not found.")
    req = request or RollbackRequest()
    updated = await svc_rollback(session, action, analyst_id=req.analyst_id, note=req.note)
    return _to_out(updated)
