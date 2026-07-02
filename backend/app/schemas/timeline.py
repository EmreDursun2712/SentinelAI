"""DTOs for the host attack-timeline API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import Severity


class TimelineEntryOut(BaseModel):
    timestamp: datetime
    kind: str  # flow | alert | triage | response
    phase: str  # Activity | Detection | Triage | Response
    title: str
    severity: Severity | None = None
    prediction: str | None = None
    label: str | None = None
    alert_id: int | None = None


class HostTimelineSummary(BaseModel):
    ip: str
    event_count: int
    alert_count: int
    response_count: int
    families: list[str] = Field(default_factory=list)
    max_severity: Severity | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class HostTimelineOut(BaseModel):
    ip: str
    window_hours: int
    summary: HostTimelineSummary
    items: list[TimelineEntryOut] = Field(default_factory=list)
