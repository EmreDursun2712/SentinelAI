"""Pydantic DTOs for the detection API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import DriftStatus
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
    # Share of the model's trained features present in the processed batch
    # (1.0 = full coverage). Low values flag a train/serve feature mismatch.
    feature_coverage: float | None = None


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
    # Declared at train time: the share of trained features the model expects to
    # see at inference. Surfaced on the dashboard model panel.
    expected_feature_coverage: float | None = None
    calibrated: bool | None = None

    model_config = ConfigDict(from_attributes=False)


# ----- Drift monitoring ---------------------------------------------------


class DriftRunRequest(BaseModel):
    window_hours: int = Field(default=24, ge=1, le=720)


class DriftSnapshotOut(BaseModel):
    id: int
    model_version_id: int | None
    window_start: datetime
    window_end: datetime
    sample_count: int
    feature_drift: dict[str, Any]
    prediction_distribution: dict[str, Any]
    confidence_stats: dict[str, Any]
    feedback: dict[str, Any] = Field(default_factory=dict)
    drift_score: float | None
    status: DriftStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("feedback", mode="before")
    @classmethod
    def _feedback_default(cls, value: Any) -> dict[str, Any]:
        # Snapshots predating feedback tracking (or not yet flushed) carry NULL.
        return value or {}


class DriftReport(BaseModel):
    """Envelope so the UI can distinguish 'no drift data' from an actual result."""

    available: bool
    reason: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    snapshot: DriftSnapshotOut | None = None


class DriftHistoryOut(BaseModel):
    items: list[DriftSnapshotOut]
