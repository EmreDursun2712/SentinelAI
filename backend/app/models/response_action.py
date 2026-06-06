"""ResponseAction — proposed (and possibly simulated-executed) response to an alert.

Ethics: `simulated` defaults to TRUE and is enforced at the database layer with a
CHECK constraint. There is no code path in the project that creates a row with
simulated=FALSE.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    false,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import ResponseActionType, ResponseStatus
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.agent_decision import AgentDecision
    from app.models.alert import Alert


class ResponseAction(TimestampMixin, Base):
    __tablename__ = "response_actions"
    __table_args__ = (
        CheckConstraint("simulated = TRUE", name="ck_response_actions_simulated_only"),
        Index("ix_response_actions_alert_id_created_at", "alert_id", "created_at"),
        Index("ix_response_actions_status_created_at", "status", "created_at"),
        Index("ix_response_actions_action_type", "action_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("agent_decisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_type: Mapped[ResponseActionType] = mapped_column(
        SAEnum(
            ResponseActionType,
            name="response_action_type_enum",
            native_enum=False,
            length=30,
        ),
        nullable=False,
    )
    simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    status: Mapped[ResponseStatus] = mapped_column(
        SAEnum(ResponseStatus, name="response_status_enum", native_enum=False, length=20),
        nullable=False,
        default=ResponseStatus.PENDING,
        server_default=ResponseStatus.PENDING.value,
    )
    executed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    approved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    alert: Mapped["Alert"] = relationship(back_populates="actions")
    decision: Mapped["AgentDecision | None"] = relationship(back_populates="actions")
