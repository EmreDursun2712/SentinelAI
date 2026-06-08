"""background task tracking table

Revision ID: 0010_tasks
Revises: 0009_account_lockout
Create Date: 2026-06-08 12:00:00.000000

Adds the ``tasks`` table backing the async worker queue (arq): one row per
background job with status, progress, params/result JSONB, error, and timestamps.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_tasks"
down_revision: str | None = "0009_account_lockout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TASK_KIND = (
    "DETECTION_RUN",
    "REPORT_ALERT",
    "DAILY_SUMMARY",
    "DRIFT_RUN",
    "RETENTION_CLEANUP",
    "ML_RETRAIN",
)
_TASK_STATUS = ("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*_TASK_KIND, name="task_kind_enum", native_enum=False, length=30),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(*_TASK_STATUS, name="task_status_enum", native_enum=False, length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("progress", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_status_created_at", "tasks", ["status", "created_at"])
    op.create_index("ix_tasks_created_by_created_at", "tasks", ["created_by", "created_at"])
    op.create_index("ix_tasks_kind_created_at", "tasks", ["kind", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_tasks_kind_created_at", table_name="tasks")
    op.drop_index("ix_tasks_created_by_created_at", table_name="tasks")
    op.drop_index("ix_tasks_status_created_at", table_name="tasks")
    op.drop_table("tasks")
