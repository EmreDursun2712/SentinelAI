"""lab-response controls: execution_mode + rollback fields, mode-aware simulated CHECK

Revision ID: 0007_lab_response_controls
Revises: 0006_model_drift_snapshots
Create Date: 2026-06-06 00:00:00.000000

Replaces the binary ``simulated = TRUE`` guardrail with a stronger, mode-aware
constraint: a row may be non-simulated ONLY in LAB mode. Existing rows default
to SIMULATED / simulated=TRUE and satisfy the new constraint unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_lab_response_controls"
down_revision: str | None = "0006_model_drift_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXECUTION_MODE = ("SIMULATED", "LAB")
_ROLLBACK_STATUS = ("NOT_REQUIRED", "AVAILABLE", "ROLLED_BACK", "FAILED")


def upgrade() -> None:
    op.add_column(
        "response_actions",
        sa.Column(
            "execution_mode",
            sa.Enum(*_EXECUTION_MODE, name="execution_mode_enum", native_enum=False, length=12),
            nullable=False,
            server_default="SIMULATED",
        ),
    )
    op.add_column(
        "response_actions", sa.Column("executor_name", sa.String(length=40), nullable=True)
    )
    op.add_column(
        "response_actions",
        sa.Column("external_execution_id", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "response_actions", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "response_actions",
        sa.Column(
            "rollback_status",
            sa.Enum(*_ROLLBACK_STATUS, name="rollback_status_enum", native_enum=False, length=15),
            nullable=False,
            server_default="NOT_REQUIRED",
        ),
    )
    op.add_column(
        "response_actions", sa.Column("rollback_payload", postgresql.JSONB(), nullable=True)
    )
    op.add_column("response_actions", sa.Column("execution_error", sa.Text(), nullable=True))

    # Swap the binary guardrail for the mode-aware one.
    op.drop_constraint("ck_response_actions_simulated_only", "response_actions", type_="check")
    op.create_check_constraint(
        "ck_response_actions_simulated_unless_lab",
        "response_actions",
        "simulated = TRUE OR execution_mode = 'LAB'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_response_actions_simulated_unless_lab", "response_actions", type_="check"
    )
    # Restoring the strict constraint requires all rows be simulated.
    op.create_check_constraint(
        "ck_response_actions_simulated_only",
        "response_actions",
        "simulated = TRUE",
    )
    for col in (
        "execution_error",
        "rollback_payload",
        "rollback_status",
        "expires_at",
        "external_execution_id",
        "executor_name",
        "execution_mode",
    ):
        op.drop_column("response_actions", col)
