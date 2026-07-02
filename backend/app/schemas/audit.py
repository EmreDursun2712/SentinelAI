"""DTOs for the unified audit trail API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuditEntryOut(BaseModel):
    id: str
    timestamp: datetime
    category: str  # auth | model | analyst | response
    actor: str | None = None
    action: str
    target: str | None = None
    detail: str | None = None


class AuditListOut(BaseModel):
    items: list[AuditEntryOut]
    has_more: bool
    limit: int
    offset: int
