"""Alert — the central row of the workflow.

The `status` column drives the agent state machine:
    NEW → TRIAGED → {AUTO_RESPONDED | AWAITING_ANALYST}
        → INVESTIGATED → REPORTED → CLOSED

The `disposition` column is orthogonal and captures the **analyst verdict**:
    OPEN → UNDER_REVIEW → {CONFIRMED | FALSE_POSITIVE | RESOLVED}
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import AlertDisposition, AlertStatus, Severity
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.agent_decision import AgentDecision
    from app.models.alert_artifact import AlertArtifact
    from app.models.incident_report import IncidentReport
    from app.models.model_version import ModelVersion
    from app.models.network_event import NetworkEvent
    from app.models.response_action import ResponseAction


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_alerts_confidence_range",
        ),
        CheckConstraint(
            "priority IS NULL OR (priority >= 0 AND priority <= 100)",
            name="ck_alerts_priority_range",
        ),
        Index("ix_alerts_status_created_at", "status", "created_at"),
        Index("ix_alerts_severity_created_at", "severity", "created_at"),
        Index("ix_alerts_src_ip", "src_ip"),
        Index("ix_alerts_dst_ip", "dst_ip"),
        Index("ix_alerts_created_at", "created_at"),
        Index("ix_alerts_model_version_id", "model_version_id"),
        Index("ix_alerts_priority_desc", text("priority DESC")),
        Index("ix_alerts_disposition_created_at", "disposition", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("network_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("model_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    src_ip: Mapped[str] = mapped_column(INET, nullable=False)
    dst_ip: Mapped[str] = mapped_column(INET, nullable=False)
    src_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dst_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protocol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    prediction: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[Severity | None] = mapped_column(
        SAEnum(Severity, name="severity_enum", native_enum=False, length=10),
        nullable=True,
    )
    priority: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[AlertStatus] = mapped_column(
        SAEnum(AlertStatus, name="alert_status_enum", native_enum=False, length=20),
        nullable=False,
        default=AlertStatus.NEW,
        server_default=AlertStatus.NEW.value,
    )
    disposition: Mapped[AlertDisposition] = mapped_column(
        SAEnum(
            AlertDisposition,
            name="alert_disposition_enum",
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=AlertDisposition.OPEN,
        server_default=AlertDisposition.OPEN.value,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    investigated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event: Mapped["NetworkEvent | None"] = relationship(back_populates="alerts")
    model_version: Mapped["ModelVersion | None"] = relationship(back_populates="alerts")
    artifacts: Mapped[list["AlertArtifact"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["AgentDecision"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
        order_by="AgentDecision.created_at",
    )
    actions: Mapped[list["ResponseAction"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
        order_by="ResponseAction.created_at",
    )
    reports: Mapped[list["IncidentReport"]] = relationship(back_populates="alert")
