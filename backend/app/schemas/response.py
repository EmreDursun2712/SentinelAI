"""Pydantic DTOs for the response/recommendation API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ResponseActionType, ResponseStatus


class ResponseActionOut(BaseModel):
    id: int
    alert_id: int
    decision_id: int | None
    action_type: ResponseActionType
    simulated: bool
    status: ResponseStatus
    executed: bool
    approval_required: bool
    approved_by: str | None
    rejection_reason: str | None
    payload: dict[str, Any]
    executed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecommendResponse(BaseModel):
    alert_id: int
    actions: list[ResponseActionOut]


class ApproveRequest(BaseModel):
    analyst_id: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)
    analyst_id: str | None = Field(default=None, max_length=80)
