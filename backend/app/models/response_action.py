"""ResponseAction — proposed (and possibly executed) response to an alert.

Ethics: ``simulated`` defaults to TRUE. A database CHECK enforces that a row may
only be non-simulated when it is a ``LAB``-mode action (``execution_mode='LAB'``)
— i.e. real effects are *structurally impossible* in the default SIMULATED mode.
LAB mode is itself gated by config (disabled by default, allowlisted CIDRs,
analyst approval) — see ``app.services.response_executors`` and ``docs/LAB_RESPONSE.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    false,
    text,
    true,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import ExecutionMode, ResponseActionType, ResponseStatus, RollbackStatus
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.agent_decision import AgentDecision
    from app.models.alert import Alert


class ResponseAction(TimestampMixin, Base):
    __tablename__ = "response_actions"
    __table_args__ = (
        # Guardrail: a row may be non-simulated ONLY in LAB mode. The default
        # SIMULATED mode can never store a real (simulated=FALSE) action.
        CheckConstraint(
            "simulated = TRUE OR execution_mode = 'LAB'",
            name="ck_response_actions_simulated_unless_lab",
        ),
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

    # Execution mode + lab-executor bookkeeping.
    execution_mode: Mapped[ExecutionMode] = mapped_column(
        SAEnum(ExecutionMode, name="execution_mode_enum", native_enum=False, length=12),
        nullable=False,
        default=ExecutionMode.SIMULATED,
        server_default=ExecutionMode.SIMULATED.value,
    )
    executor_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    external_execution_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_status: Mapped[RollbackStatus] = mapped_column(
        SAEnum(RollbackStatus, name="rollback_status_enum", native_enum=False, length=15),
        nullable=False,
        default=RollbackStatus.NOT_REQUIRED,
        server_default=RollbackStatus.NOT_REQUIRED.value,
    )
    rollback_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    execution_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    alert: Mapped[Alert] = relationship(back_populates="actions")
    decision: Mapped[AgentDecision | None] = relationship(back_populates="actions")
