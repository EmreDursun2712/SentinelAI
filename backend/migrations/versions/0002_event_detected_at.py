"""add network_events.detected_at + partial index

Revision ID: 0002_event_detected_at
Revises: 0001_initial_schema
Create Date: 2026-05-20 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_event_detected_at"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "network_events",
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index — supports the hot path "next batch of un-detected events".
    op.create_index(
        "ix_network_events_undetected_created_at",
        "network_events",
        ["created_at"],
        postgresql_where=sa.text("detected_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_network_events_undetected_created_at", table_name="network_events"
    )
    op.drop_column("network_events", "detected_at")
