"""Pydantic DTOs for the reporting API.

A ``ReportPacket`` is what the Reporting agent persists into
``incident_reports.summary`` (JSONB) — it is *also* what the API returns, so
the dashboard never has to know about the on-disk markdown file. The
``markdown`` field carries the rendered version inline.
"""

from __future__ import annotations

from datetime import date as date_t, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AlertDisposition,
    AlertStatus,
    IncidentKind,
    ResponseActionType,
    ResponseStatus,
    Severity,
)
from app.schemas.common import IpString


# ---------- per-section payloads -----------------------------------------


class OverviewSection(BaseModel):
    alert_id: int
    created_at: datetime
    src_ip: IpString
    src_port: int | None = None
    dst_ip: IpString
    dst_port: int | None = None
    protocol: str | None = None
    prediction: str
    model_name: str | None = None
    model_version: str | None = None


class TriageFactors(BaseModel):
    family: str | None = None
    family_score: float | None = None
    confidence_score: float | None = None
    dst_port: int | None = None
    port_score: float | None = None
    volume_score: float | None = None


class SeverityPrioritySection(BaseModel):
    severity: Severity | None = None
    priority: float | None = None
    factors: TriageFactors = Field(default_factory=TriageFactors)
    component_weights: dict[str, float] = Field(default_factory=dict)
    explanations: list[str] = Field(default_factory=list)
    triaged_at: datetime | None = None


class DetectionSection(BaseModel):
    predicted_label: str
    confidence: float
    threshold: float | None = None
    class_probabilities: dict[str, float] = Field(default_factory=dict)
    model_name: str | None = None
    model_version: str | None = None


class FeatureImportanceItem(BaseModel):
    feature: str
    importance: float


class InvestigationSection(BaseModel):
    available: bool
    summary: str | None = None
    bullets: list[str] = Field(default_factory=list)
    statistics: dict[str, Any] = Field(default_factory=dict)
    feature_importance: list[FeatureImportanceItem] = Field(default_factory=list)
    generated_at: datetime | None = None


class TimelineRow(BaseModel):
    timestamp: datetime
    kind: str  # event / alert / agent / analyst
    summary: str
    is_current_alert: bool = False


class TimelineSection(BaseModel):
    items: list[TimelineRow] = Field(default_factory=list)


class ResponseActionRow(BaseModel):
    id: int
    action_type: ResponseActionType
    status: ResponseStatus
    approval_required: bool
    executed: bool
    approved_by: str | None = None
    rejection_reason: str | None = None
    rationale: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime | None = None
    created_at: datetime


class ResponseSection(BaseModel):
    actions: list[ResponseActionRow] = Field(default_factory=list)
    counts_by_status: dict[str, int] = Field(default_factory=dict)
    auto_executed: int = 0
    awaiting_approval: int = 0
    rejected: int = 0


class AnalystEntry(BaseModel):
    timestamp: datetime
    analyst_id: str | None = None
    verb: str  # approve / reject / disposition / note
    target: str | None = None
    note: str | None = None
    detail: str


class AnalystSection(BaseModel):
    status: AlertStatus
    disposition: AlertDisposition
    entries: list[AnalystEntry] = Field(default_factory=list)


# ---------- top-level packet ---------------------------------------------


class AlertReportPacket(BaseModel):
    """Per-alert report — stored in ``incident_reports.summary`` JSONB."""

    alert_id: int
    report_id: int | None = None
    kind: IncidentKind = IncidentKind.PER_ALERT
    title: str
    generated_at: datetime
    workflow_status: AlertStatus
    disposition: AlertDisposition
    overview: OverviewSection
    severity_priority: SeverityPrioritySection
    detection: DetectionSection | None = None
    investigation: InvestigationSection
    timeline: TimelineSection
    response: ResponseSection
    analyst: AnalystSection
    final_summary: str
    markdown: str

    model_config = ConfigDict(from_attributes=False)


class DailySummaryPacket(BaseModel):
    """Daily roll-up — also stored in ``incident_reports.summary`` JSONB."""

    report_id: int | None = None
    kind: IncidentKind = IncidentKind.DAILY_SUMMARY
    title: str
    generated_at: datetime
    date: date_t
    period_start: datetime
    period_end: datetime
    total_alerts: int
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_disposition: dict[str, int] = Field(default_factory=dict)
    top_sources: list[dict[str, Any]] = Field(default_factory=list)
    top_destinations: list[dict[str, Any]] = Field(default_factory=list)
    top_predictions: list[dict[str, Any]] = Field(default_factory=list)
    response_actions_total: int = 0
    response_actions_by_type: dict[str, int] = Field(default_factory=dict)
    response_actions_by_status: dict[str, int] = Field(default_factory=dict)
    mean_triage_latency_seconds: float | None = None
    mean_response_latency_seconds: float | None = None
    mean_investigation_latency_seconds: float | None = None
    mean_report_latency_seconds: float | None = None
    final_summary: str
    markdown: str

    model_config = ConfigDict(from_attributes=False)


# ---------- request / response shapes -------------------------------------


class ReportRequest(BaseModel):
    """Body for ``POST /api/v1/alerts/{id}/report`` — currently no knobs."""

    # Placeholder for future report-style toggles (e.g. minimal vs full).
    pass


class DailySummaryRequest(BaseModel):
    date: date_t | None = None  # default: today (UTC)


class IncidentReportOut(BaseModel):
    """Lightweight summary row for ``GET /api/v1/reports``."""

    id: int
    kind: IncidentKind
    alert_id: int | None
    title: str
    period_start: datetime | None
    period_end: datetime | None
    md_path: str | None
    pdf_path: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertReportEnvelope(BaseModel):
    report_id: int
    packet: AlertReportPacket


class DailySummaryEnvelope(BaseModel):
    report_id: int
    packet: DailySummaryPacket
