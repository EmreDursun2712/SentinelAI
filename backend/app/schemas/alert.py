"""Pydantic DTOs for the alerts API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentName, AlertDisposition, AlertStatus, Severity
from app.schemas.common import IpString
from app.schemas.response import ResponseActionOut


class AlertOut(BaseModel):
    id: int
    src_ip: IpString
    dst_ip: IpString
    src_port: int | None
    dst_port: int | None
    protocol: str | None
    prediction: str
    confidence: float
    severity: Severity | None
    priority: float | None
    status: AlertStatus
    disposition: AlertDisposition
    event_id: int | None
    model_version_id: int | None
    notes: str | None
    triaged_at: datetime | None
    responded_at: datetime | None
    investigated_at: datetime | None
    reported_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TriageRequest(BaseModel):
    """Body for ``POST /api/v1/alerts/{id}/triage`` — manual re-triage."""

    window_minutes: int = Field(default=15, ge=1, le=1440)


class TriageOut(BaseModel):
    """Audit-trail-friendly response from the triage endpoint."""

    alert_id: int
    severity: Severity
    priority: float
    recent_count: int
    component_weights: dict[str, float]
    factors: dict[str, Any]
    explanations: list[str]


class UpdateDispositionRequest(BaseModel):
    disposition: AlertDisposition
    note: str | None = Field(default=None, max_length=2000)
    analyst_id: str | None = Field(default=None, max_length=80)


class CloseAlertRequest(BaseModel):
    """Body for ``POST /api/v1/alerts/{id}/close`` — all fields optional."""

    note: str | None = Field(default=None, max_length=2000)
    analyst_id: str | None = Field(default=None, max_length=80)


class AlertDecisionOut(BaseModel):
    id: int
    agent: AgentName
    decision: dict[str, Any]
    reasoning: dict[str, Any]
    latency_ms: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertDetailOut(AlertOut):
    """Alert plus its agent-decision audit trail and response actions."""

    decisions: list[AlertDecisionOut] = Field(default_factory=list)
    actions: list[ResponseActionOut] = Field(default_factory=list)


class AlertStatsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    by_disposition: dict[str, int]
    by_prediction: dict[str, int] = Field(default_factory=dict)


class AlertTimeseriesPoint(BaseModel):
    """One time-bucket of alert counts, broken down by severity.

    Fields use the same uppercase names as the ``Severity`` enum so the
    frontend chart can key directly into them.
    """

    bucket: datetime
    LOW: int = 0
    MEDIUM: int = 0
    HIGH: int = 0
    CRITICAL: int = 0
    UNRATED: int = 0
    total: int = 0


class AlertTimeseriesOut(BaseModel):
    bucket: str  # currently "hour"
    period_hours: int
    points: list[AlertTimeseriesPoint] = Field(default_factory=list)


class DashboardOverviewOut(BaseModel):
    """Single payload powering the SOC dashboard's KPI cards + charts."""

    total_events: int
    suspicious_events: int  # alias for alerts.total — clearer in dashboard context
    open_alerts: int
    critical_alerts: int
    high_alerts: int
    pending_actions: int
    alerts: AlertStatsOut
