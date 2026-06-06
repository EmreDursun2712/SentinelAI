"""Pydantic DTOs for the detection API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.ingestion import FlowRecordIn


class PredictionOut(BaseModel):
    event_id: int | None = None
    predicted_label: str
    confidence: float
    class_probabilities: dict[str, float]
    threshold: float
    benign: bool
    alert_created: bool
    alert_id: int | None = None


class PredictRequest(BaseModel):
    flows: list[FlowRecordIn] = Field(..., min_length=1, max_length=500)


class BatchEventRequest(BaseModel):
    event_ids: list[int] = Field(..., min_length=1, max_length=500)


class RunRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=10_000)


class RunSummary(BaseModel):
    processed: int
    alerts_created: int
    benign_count: int
    by_label: dict[str, int]
    model_name: str
    model_version: str


class ModelInfoOut(BaseModel):
    loaded: bool
    name: str | None = None
    version: str | None = None
    algorithm: str | None = None
    classes: list[str] = Field(default_factory=list)
    feature_order: list[str] = Field(default_factory=list)
    metrics_summary: dict[str, Any] = Field(default_factory=dict)
    artifact_dir: str | None = None
    loaded_at: datetime | None = None
    db_id: int | None = None
    is_active: bool | None = None
    threshold: float | None = None
    benign_label: str | None = None

    model_config = ConfigDict(from_attributes=False)
