"""extend response_actions.action_type with ESCALATE / ISOLATE_ALERT / SUPPRESS_ALERT / CREATE_TICKET

Revision ID: 0004_response_action_types
Revises: 0003_triage_and_disposition
Create Date: 2026-05-21 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa  # noqa: F401 — kept for consistency with sibling migrations
from alembic import op

revision: str = "0004_response_action_types"
down_revision: str | None = "0003_triage_and_disposition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_ACTION_TYPES = (
    "BLOCK_IP",
    "RATE_LIMIT",
    "ISOLATE_HOST",
    "NOTIFY_ANALYST",
    "NO_ACTION",
    "ESCALATE",
    "ISOLATE_ALERT",
    "SUPPRESS_ALERT",
    "CREATE_TICKET",
)
_OLD_ACTION_TYPES = (
    "BLOCK_IP",
    "RATE_LIMIT",
    "ISOLATE_HOST",
    "NOTIFY_ANALYST",
    "NO_ACTION",
)


def _check_expression(values: tuple[str, ...]) -> str:
    quoted = ",".join(f"'{v}'" for v in values)
    return f"action_type IN ({quoted})"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE response_actions DROP CONSTRAINT IF EXISTS response_action_type_enum"
    )
    op.create_check_constraint(
        "response_action_type_enum",
        "response_actions",
        _check_expression(_NEW_ACTION_TYPES),
    )


def downgrade() -> None:
    # Any rows using the new action types must be deleted/migrated before this
    # downgrade succeeds — otherwise the CHECK creation will fail loudly.
    op.execute(
        "ALTER TABLE response_actions DROP CONSTRAINT IF EXISTS response_action_type_enum"
    )
    op.create_check_constraint(
        "response_action_type_enum",
        "response_actions",
        _check_expression(_OLD_ACTION_TYPES),
    )
