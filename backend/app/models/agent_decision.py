"""AgentDecision — one row per (alert, agent) step.

Acts as the audit trail of the workflow: every agent that touches an alert leaves
a structured record of what it decided and why.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Enum as SAEnum, ForeignKey, Index, Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import AgentName
from app.models.mixins import CreatedAtMixin

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.response_action import ResponseAction


class AgentDecision(CreatedAtMixin, Base):
    __tablename__ = "agent_decisions"
    __table_args__ = (
        Index("ix_agent_decisions_alert_id_created_at", "alert_id", "created_at"),
        Index("ix_agent_decisions_agent_created_at", "agent", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent: Mapped[AgentName] = mapped_column(
        SAEnum(AgentName, name="agent_name_enum", native_enum=False, length=20),
        nullable=False,
    )
    decision: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    reasoning: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    alert: Mapped["Alert"] = relationship(back_populates="decisions")
    actions: Mapped[list["ResponseAction"]] = relationship(back_populates="decision")
