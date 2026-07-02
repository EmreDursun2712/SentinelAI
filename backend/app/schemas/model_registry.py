"""Pydantic DTOs for the model registry / lifecycle API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelVersionOut(BaseModel):
    id: int
    name: str
    version: str
    algorithm: str
    classes: list[str] = Field(default_factory=list)
    feature_order: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str
    is_active: bool
    trained_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModelVersionListOut(BaseModel):
    items: list[ModelVersionOut]
    active_version_id: int | None = None


class ActivateRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RollbackRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ActivationResult(BaseModel):
    """Outcome of an activate/rollback: the now-active version + whether the
    artifact was loaded into this process's in-memory registry."""

    action: str
    loaded: bool
    version: ModelVersionOut


class ModelActivationOut(BaseModel):
    id: int
    model_version_id: int | None
    previous_version_id: int | None
    action: str
    actor: str | None
    reason: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModelActivationListOut(BaseModel):
    items: list[ModelActivationOut]


class ShadowEvalRequest(BaseModel):
    candidate_version_id: int
    window_hours: int = Field(default=24, ge=1, le=720)


class PromoteRequest(BaseModel):
    candidate_version_id: int
    window_hours: int = Field(default=24, ge=1, le=720)


class ShadowEvalOut(BaseModel):
    id: int
    candidate_version_id: int | None
    active_version_id: int | None
    window_start: datetime
    window_end: datetime
    sample_count: int
    agreement_rate: float | None
    metrics: dict[str, Any] = Field(default_factory=dict)
    # Lifted out of ``metrics`` for convenience: the promote/hold recommendation
    # ({"decision": ...}) computed from the label-aware A/B comparison.
    recommendation: dict[str, Any] | None = None
    created_by: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _lift_recommendation(self) -> ShadowEvalOut:
        if self.recommendation is None and isinstance(self.metrics, dict):
            self.recommendation = self.metrics.get("recommendation")
        return self


class PromoteResult(BaseModel):
    """Outcome of an auto-promote attempt: the eval + whether it activated."""

    promoted: bool
    active_version_id: int | None
    evaluation: ShadowEvalOut
