"""IncidentReport — per-alert or daily-summary write-up produced by the Reporting Agent."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import IncidentKind
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.alert import Alert


class IncidentReport(TimestampMixin, Base):
    __tablename__ = "incident_reports"
    __table_args__ = (
        Index("ix_incident_reports_kind_created_at", "kind", "created_at"),
        Index("ix_incident_reports_alert_id", "alert_id"),
        Index("ix_incident_reports_period_start", "period_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[IncidentKind] = mapped_column(
        SAEnum(IncidentKind, name="incident_kind_enum", native_enum=False, length=20),
        nullable=False,
    )
    alert_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("alerts.id", ondelete="SET NULL"),
        nullable=True,
    )
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    md_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    alert: Mapped[Alert | None] = relationship(back_populates="reports")
