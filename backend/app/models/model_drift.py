"""ModelDriftSnapshot — one drift evaluation of recent traffic vs the baseline.

Each row records, for a time window, how far recent network-flow features and
model predictions have drifted from the training baseline embedded in the active
model artifact. The structured detail lives in JSONB columns; ``drift_score`` +
``status`` are the at-a-glance summary the dashboard shows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    func,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import DriftStatus


class ModelDriftSnapshot(Base):
    __tablename__ = "model_drift_snapshots"
    __table_args__ = (
        Index("ix_model_drift_snapshots_model_version_id", "model_version_id"),
        Index("ix_model_drift_snapshots_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("model_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    feature_drift: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    prediction_distribution: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    confidence_stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    drift_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[DriftStatus] = mapped_column(
        SAEnum(DriftStatus, name="drift_status_enum", native_enum=False, length=10),
        nullable=False,
        default=DriftStatus.OK,
        server_default=DriftStatus.OK.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
