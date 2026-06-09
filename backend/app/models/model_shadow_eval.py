"""ModelShadowEval — one shadow (A/B) comparison of a candidate vs. active model.

Shadow evaluation runs a candidate model over recent events **without** changing
which model serves production traffic, then records how its predictions compare
to the currently active model: agreement rate, per-label distribution deltas, and
mean-confidence delta. Persisting each run lets analysts decide whether a
candidate is worth activating before flipping the switch.
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
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ModelShadowEval(Base):
    __tablename__ = "model_shadow_evals"
    __table_args__ = (Index("ix_model_shadow_evals_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="SET NULL"), nullable=True
    )
    active_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="SET NULL"), nullable=True
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agreement_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
