"""model lifecycle: drift feedback + activation audit + shadow evals

Revision ID: 0012_model_lifecycle
Revises: 0011_soft_delete_archive
Create Date: 2026-06-08 16:00:00.000000

Adds:
* ``model_drift_snapshots.feedback`` — analyst-disposition quality proxy (JSONB).
* ``model_activations`` — append-only audit of activate/rollback decisions.
* ``model_shadow_evals`` — persisted candidate-vs-active shadow comparisons.

See docs/MODEL_LIFECYCLE.md.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012_model_lifecycle"
down_revision: str | None = "0011_soft_delete_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_drift_snapshots",
        sa.Column(
            "feedback",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "model_activations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "model_version_id",
            sa.BigInteger(),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "previous_version_id",
            sa.BigInteger(),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_model_activations_created_at", "model_activations", ["created_at"])

    op.create_table(
        "model_shadow_evals",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "candidate_version_id",
            sa.BigInteger(),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "active_version_id",
            sa.BigInteger(),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("agreement_rate", sa.Float(), nullable=True),
        sa.Column(
            "metrics",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_model_shadow_evals_created_at", "model_shadow_evals", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_model_shadow_evals_created_at", table_name="model_shadow_evals")
    op.drop_table("model_shadow_evals")
    op.drop_index("ix_model_activations_created_at", table_name="model_activations")
    op.drop_table("model_activations")
    op.drop_column("model_drift_snapshots", "feedback")
