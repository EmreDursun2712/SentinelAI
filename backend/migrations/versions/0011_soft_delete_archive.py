"""soft-delete (archived_at) on alerts + incident_reports

Revision ID: 0011_soft_delete_archive
Revises: 0010_tasks
Create Date: 2026-06-08 13:30:00.000000

Adds an ``archived_at`` marker used by data retention to soft-delete alerts and
reports (hidden from default lists, preserved for audit). Existing rows default
to NULL (active). See docs/DATA_RETENTION.md.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_soft_delete_archive"
down_revision: str | None = "0010_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "incident_reports", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Partial index for the "active (non-archived)" alert list.
    op.create_index(
        "ix_alerts_active_created_at",
        "alerts",
        ["created_at"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_active_created_at", table_name="alerts")
    op.drop_column("incident_reports", "archived_at")
    op.drop_column("alerts", "archived_at")
