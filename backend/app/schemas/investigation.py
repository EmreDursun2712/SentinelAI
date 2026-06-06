"""Pydantic DTOs for the investigation API.

Everything here is JSON-friendly so the same shape that goes into the
``alert_artifacts.data`` JSONB column can also be returned from the API
unchanged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Severity
from app.schemas.common import IpString


# ---------- request / config ----------------------------------------------


class InvestigateRequest(BaseModel):
    """Body for ``POST /api/v1/alerts/{id}/investigate`` — optional overrides."""

    # Window around the alert's created_at used when fetching related flows.
    events_window_minutes: int = Field(default=60, ge=1, le=10_080)
    # How far back to look for related alerts (same src/dst/family).
    alerts_window_hours: int = Field(default=24, ge=1, le=720)
    # Hard caps on the rows we materialize into the packet.
    max_events: int = Field(default=200, ge=1, le=2_000)
    max_alerts: int = Field(default=50, ge=1, le=500)


# ---------- payload pieces -------------------------------------------------


class RelatedAlertOut(BaseModel):
    id: int
    src_ip: IpString
    dst_ip: IpString
    src_port: int | None = None
    dst_port: int | None = None
    protocol: str | None = None
    prediction: str
    severity: Severity | None = None
    priority: float | None = None
    confidence: float
    created_at: datetime


class RelatedEventOut(BaseModel):
    id: int
    event_time: datetime
    src_ip: IpString
    dst_ip: IpString
    src_port: int | None = None
    dst_port: int | None = None
    protocol: str | None = None
    label: str | None = None


class TimelineItem(BaseModel):
    timestamp: datetime
    kind: Literal["event", "alert"]
    summary: str
    src_ip: IpString | None = None
    dst_ip: IpString | None = None
    label: str | None = None
    prediction: str | None = None
    severity: Severity | None = None
    alert_id: int | None = None
    is_current_alert: bool = False


class InvestigationStatistics(BaseModel):
    related_event_count: int
    related_alert_count: int
    distinct_source_ips: int
    distinct_destination_ips: int
    same_src_ip_alert_count: int
    same_dst_ip_alert_count: int
    same_family_alert_count: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    activity_span_seconds: float | None = None
    top_label: str | None = None
    top_prediction: str | None = None


class FeatureImportanceItem(BaseModel):
    feature: str
    importance: float


# ---------- top-level packet ----------------------------------------------


class InvestigationPacket(BaseModel):
    """Stored verbatim in ``alert_artifacts.data`` and returned by the API."""

    alert_id: int
    generated_at: datetime
    events_window_minutes: int
    alerts_window_hours: int
    summary: str
    summary_bullets: list[str] = Field(default_factory=list)
    statistics: InvestigationStatistics
    related_alerts: list[RelatedAlertOut] = Field(default_factory=list)
    related_events: list[RelatedEventOut] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)
    feature_importance: list[FeatureImportanceItem] = Field(default_factory=list)
    model_name: str | None = None
    model_version: str | None = None
    truncated: bool = False  # set when results hit max_events / max_alerts caps

    model_config = ConfigDict(from_attributes=False)


class InvestigationOut(BaseModel):
    """Wraps the packet with the artifact id for traceability."""

    artifact_id: int
    packet: InvestigationPacket
