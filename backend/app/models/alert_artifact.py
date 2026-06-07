"""AlertArtifact — auxiliary data attached to an alert by agents or analysts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Index, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import ArtifactKind
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.alert import Alert


class AlertArtifact(CreatedAtMixin, Base):
    __tablename__ = "alert_artifacts"
    __table_args__ = (Index("ix_alert_artifacts_alert_id_kind", "alert_id", "kind"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[ArtifactKind] = mapped_column(
        SAEnum(ArtifactKind, name="artifact_kind_enum", native_enum=False, length=30),
        nullable=False,
    )
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    alert: Mapped[Alert] = relationship(back_populates="artifacts")
