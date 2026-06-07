"""NetworkEvent — normalized flow record consumed by the Detection Agent."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.ingestion_job import IngestionJob


class NetworkEvent(CreatedAtMixin, Base):
    """Flow records are immutable except for the ``detected_at`` marker the
    Detection Agent sets once it has classified the event."""

    __tablename__ = "network_events"
    __table_args__ = (
        Index("ix_network_events_event_time", "event_time"),
        Index("ix_network_events_src_ip", "src_ip"),
        Index("ix_network_events_dst_ip", "dst_ip"),
        Index("ix_network_events_ingestion_job_id", "ingestion_job_id"),
        Index(
            "ix_network_events_undetected_created_at",
            "created_at",
            postgresql_where=text("detected_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ingestion_job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    src_ip: Mapped[str] = mapped_column(INET, nullable=False)
    dst_ip: Mapped[str] = mapped_column(INET, nullable=False)
    src_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dst_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protocol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ingestion_job: Mapped[IngestionJob | None] = relationship(back_populates="events")
    alerts: Mapped[list[Alert]] = relationship(back_populates="event")
