"""ModelActivation — audit trail for model-version activate / rollback decisions.

Every time an admin activates a model version (or rolls back to the previous
one), a row is written here recording who did it, which version became active,
which one it replaced, and why. This is append-only: artifacts and version rows
are never deleted, so the activation history is a complete, auditable record of
which model served traffic when.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ModelActivation(Base):
    __tablename__ = "model_activations"
    __table_args__ = (Index("ix_model_activations_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The version that became active. SET NULL keeps the audit row even if the
    # version row is ever removed (artifacts themselves are never deleted).
    model_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="SET NULL"), nullable=True
    )
    # The version that was active immediately before (the rollback target).
    previous_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # activate | rollback
    actor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
