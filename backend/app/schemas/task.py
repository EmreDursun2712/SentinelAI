"""Pydantic DTOs for background tasks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TaskKind, TaskStatus


class TaskOut(BaseModel):
    id: str
    kind: TaskKind
    status: TaskStatus
    progress: int
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TaskListOut(BaseModel):
    items: list[TaskOut]


class DetectionRunTaskRequest(BaseModel):
    limit: int = Field(default=1000, ge=1, le=100_000)


class DriftRunTaskRequest(BaseModel):
    window_hours: int = Field(default=24, ge=1, le=720)


class ReportAlertTaskRequest(BaseModel):
    alert_id: int = Field(ge=1)


class RetentionCleanupTaskRequest(BaseModel):
    days: int = Field(default=90, ge=1, le=3650)


class RetrainTaskRequest(BaseModel):
    synthetic: int = Field(default=20000, ge=1000, le=1_000_000)
