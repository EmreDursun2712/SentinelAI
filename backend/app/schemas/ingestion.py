"""Pydantic DTOs for the ingestion API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import IngestionKind, IngestionStatus
from app.schemas.common import IpString


class FlowRecordIn(BaseModel):
    """Single-flow ingest payload used by ``POST /api/v1/ingest/flow``."""

    event_time: datetime
    src_ip: IpString
    dst_ip: IpString
    src_port: int | None = None
    dst_port: int | None = None
    protocol: str | None = None
    label: str | None = None
    features: dict[str, Any] = Field(default_factory=dict)


class FlowRecordOut(BaseModel):
    id: int
    event_time: datetime
    src_ip: IpString
    dst_ip: IpString
    src_port: int | None
    dst_port: int | None
    protocol: str | None
    label: str | None

    model_config = ConfigDict(from_attributes=True)


class RowErrorOut(BaseModel):
    row_number: int
    message: str


class IngestionSummary(BaseModel):
    """Result of a single ingestion job."""

    job_id: int
    status: IngestionStatus
    source: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    errors: list[RowErrorOut] = Field(default_factory=list)
    errors_truncated: bool = False


class ReplayRequest(BaseModel):
    """Body for ``POST /api/v1/ingest/replay``.

    ``file`` is a path *relative to the ingest data directory*; absolute paths
    or ``..`` traversal are rejected at the endpoint.
    """

    file: str = Field(..., min_length=1, max_length=300)
    rate: int = Field(default=50, ge=1, le=10_000)


class IngestionJobOut(BaseModel):
    id: int
    kind: IngestionKind
    source: str
    status: IngestionStatus
    rate_limit: int | None
    records_total: int | None
    records_done: int
    records_failed: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
