"""triage: alerts.priority + alerts.disposition + ANALYST in agent_decisions.agent

Revision ID: 0003_triage_and_disposition
Revises: 0002_event_detected_at
Create Date: 2026-05-20 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_triage_and_disposition"
down_revision: str | None = "0002_event_detected_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DISPOSITIONS = ("OPEN", "UNDER_REVIEW", "CONFIRMED", "FALSE_POSITIVE", "RESOLVED")


def upgrade() -> None:
    # 1) alerts.priority — float 0..100, nullable until first triage.
    op.add_column("alerts", sa.Column("priority", sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_alerts_priority_range",
        "alerts",
        "priority IS NULL OR (priority >= 0 AND priority <= 100)",
    )
    op.create_index(
        "ix_alerts_priority_desc",
        "alerts",
        [sa.text("priority DESC")],
    )

    # 2) alerts.disposition — analyst verdict, OPEN by default.
    op.add_column(
        "alerts",
        sa.Column(
            "disposition",
            sa.Enum(
                *_DISPOSITIONS,
                name="alert_disposition_enum",
                native_enum=False,
                length=20,
            ),
            nullable=False,
            server_default="OPEN",
        ),
    )
    op.create_index(
        "ix_alerts_disposition_created_at",
        "alerts",
        ["disposition", "created_at"],
    )

    # 3) Extend agent_decisions.agent CHECK so analyst actions can use the
    #    same audit table. Drop + recreate the CHECK with the new value set.
    op.execute("ALTER TABLE agent_decisions DROP CONSTRAINT IF EXISTS agent_name_enum")
    op.create_check_constraint(
        "agent_name_enum",
        "agent_decisions",
        "agent IN ('DETECTION', 'TRIAGE', 'RESPONSE', 'INVESTIGATION', 'REPORTING', 'ANALYST')",
    )


def downgrade() -> None:
    # Revert the agent enum first so any stray ANALYST rows cause loud failure.
    op.execute("ALTER TABLE agent_decisions DROP CONSTRAINT IF EXISTS agent_name_enum")
    op.create_check_constraint(
        "agent_name_enum",
        "agent_decisions",
        "agent IN ('DETECTION', 'TRIAGE', 'RESPONSE', 'INVESTIGATION', 'REPORTING')",
    )

    op.drop_index("ix_alerts_disposition_created_at", table_name="alerts")
    op.drop_column("alerts", "disposition")

    op.drop_index("ix_alerts_priority_desc", table_name="alerts")
    op.drop_constraint("ck_alerts_priority_range", "alerts", type_="check")
    op.drop_column("alerts", "priority")
