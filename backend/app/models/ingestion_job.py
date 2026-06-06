"""IngestionJob — one row per CSV replay or future live ingestion run."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import IngestionKind, IngestionStatus
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.network_event import NetworkEvent


class IngestionJob(TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("ix_ingestion_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[IngestionKind] = mapped_column(
        SAEnum(IngestionKind, name="ingestion_kind_enum", native_enum=False, length=10),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[IngestionStatus] = mapped_column(
        SAEnum(IngestionStatus, name="ingestion_status_enum", native_enum=False, length=20),
        nullable=False,
        default=IngestionStatus.PENDING,
        server_default=IngestionStatus.PENDING.value,
    )
    rate_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    records_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["NetworkEvent"]] = relationship(back_populates="ingestion_job")
