"""Schemas for lightweight client-side telemetry."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClientErrorIn(BaseModel):
    """A client-side (frontend) error reported by the ErrorBoundary."""

    message: str = Field(..., max_length=2000)
    stack: str | None = Field(default=None, max_length=8000)
    component_stack: str | None = Field(default=None, max_length=8000)
    url: str | None = Field(default=None, max_length=1000)
