"""model_drift_snapshots table for drift monitoring

Revision ID: 0006_model_drift_snapshots
Revises: 0005_users_and_roles
Create Date: 2026-06-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_model_drift_snapshots"
down_revision: str | None = "0005_users_and_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DRIFT_STATUS = ("OK", "WATCH", "DRIFT")


def upgrade() -> None:
    op.create_table(
        "model_drift_snapshots",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column(
            "model_version_id",
            sa.BigInteger(),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "feature_drift", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "prediction_distribution",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "confidence_stats",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("drift_score", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*_DRIFT_STATUS, name="drift_status_enum", native_enum=False, length=10),
            nullable=False,
            server_default="OK",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_model_drift_snapshots_model_version_id",
        "model_drift_snapshots",
        ["model_version_id"],
    )
    op.create_index(
        "ix_model_drift_snapshots_created_at",
        "model_drift_snapshots",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_drift_snapshots_created_at", table_name="model_drift_snapshots")
    op.drop_index(
        "ix_model_drift_snapshots_model_version_id", table_name="model_drift_snapshots"
    )
    op.drop_table("model_drift_snapshots")
