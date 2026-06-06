"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-18 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum values are frozen in the migration on purpose: future migrations can add
# new values explicitly without back-rewriting history.
_SEVERITY = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
_ALERT_STATUS = (
    "NEW",
    "TRIAGED",
    "AUTO_RESPONDED",
    "AWAITING_ANALYST",
    "INVESTIGATED",
    "REPORTED",
    "CLOSED",
)
_INGEST_KIND = ("REPLAY", "STREAM")
_INGEST_STATUS = ("PENDING", "RUNNING", "COMPLETED", "FAILED")
_AGENT_NAME = ("DETECTION", "TRIAGE", "RESPONSE", "INVESTIGATION", "REPORTING")
_ARTIFACT_KIND = (
    "INVESTIGATION_PACKET",
    "FEATURE_IMPORTANCE",
    "RELATED_ALERTS",
    "RAW_FLOW",
    "ATTACHMENT",
)
_ACTION_TYPE = (
    "BLOCK_IP",
    "RATE_LIMIT",
    "ISOLATE_HOST",
    "NOTIFY_ANALYST",
    "NO_ACTION",
)
_ACTION_STATUS = ("PENDING", "APPROVED", "REJECTED", "EXECUTED")
_INCIDENT_KIND = ("PER_ALERT", "DAILY_SUMMARY")


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column(
            "kind",
            sa.Enum(*_INGEST_KIND, name="ingestion_kind_enum", native_enum=False, length=10),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_INGEST_STATUS, name="ingestion_status_enum", native_enum=False, length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("rate_limit", sa.Integer(), nullable=True),
        sa.Column("records_total", sa.Integer(), nullable=True),
        sa.Column("records_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_ingestion_jobs_status_created_at",
        "ingestion_jobs",
        ["status", "created_at"],
    )

    op.create_table(
        "model_versions",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("algorithm", sa.String(length=60), nullable=False),
        sa.Column(
            "classes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "feature_order",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "metrics",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("name", "version", name="uq_model_versions_name_version"),
    )
    op.create_index("ix_model_versions_name", "model_versions", ["name"])
    # Partial unique index: at most one model_versions row may have is_active = TRUE.
    op.create_index(
        "uq_model_versions_one_active",
        "model_versions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = TRUE"),
    )

    op.create_table(
        "network_events",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column(
            "ingestion_job_id",
            sa.BigInteger(),
            sa.ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("src_ip", postgresql.INET(), nullable=False),
        sa.Column("dst_ip", postgresql.INET(), nullable=False),
        sa.Column("src_port", sa.Integer(), nullable=True),
        sa.Column("dst_port", sa.Integer(), nullable=True),
        sa.Column("protocol", sa.String(length=16), nullable=True),
        sa.Column(
            "features",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("label", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_network_events_event_time", "network_events", ["event_time"])
    op.create_index("ix_network_events_src_ip", "network_events", ["src_ip"])
    op.create_index("ix_network_events_dst_ip", "network_events", ["dst_ip"])
    op.create_index(
        "ix_network_events_ingestion_job_id", "network_events", ["ingestion_job_id"]
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey("network_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "model_version_id",
            sa.BigInteger(),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("src_ip", postgresql.INET(), nullable=False),
        sa.Column("dst_ip", postgresql.INET(), nullable=False),
        sa.Column("src_port", sa.Integer(), nullable=True),
        sa.Column("dst_port", sa.Integer(), nullable=True),
        sa.Column("protocol", sa.String(length=16), nullable=True),
        sa.Column("prediction", sa.String(length=60), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(*_SEVERITY, name="severity_enum", native_enum=False, length=10),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(*_ALERT_STATUS, name="alert_status_enum", native_enum=False, length=20),
            nullable=False,
            server_default="NEW",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("investigated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_alerts_confidence_range"
        ),
    )
    op.create_index("ix_alerts_status_created_at", "alerts", ["status", "created_at"])
    op.create_index("ix_alerts_severity_created_at", "alerts", ["severity", "created_at"])
    op.create_index("ix_alerts_src_ip", "alerts", ["src_ip"])
    op.create_index("ix_alerts_dst_ip", "alerts", ["dst_ip"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])
    op.create_index("ix_alerts_model_version_id", "alerts", ["model_version_id"])

    op.create_table(
        "alert_artifacts",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column(
            "alert_id",
            sa.BigInteger(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(*_ARTIFACT_KIND, name="artifact_kind_enum", native_enum=False, length=30),
            nullable=False,
        ),
        sa.Column(
            "data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_alert_artifacts_alert_id_kind", "alert_artifacts", ["alert_id", "kind"]
    )

    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column(
            "alert_id",
            sa.BigInteger(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent",
            sa.Enum(*_AGENT_NAME, name="agent_name_enum", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column(
            "decision",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "reasoning",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_agent_decisions_alert_id_created_at",
        "agent_decisions",
        ["alert_id", "created_at"],
    )
    op.create_index(
        "ix_agent_decisions_agent_created_at",
        "agent_decisions",
        ["agent", "created_at"],
    )

    op.create_table(
        "response_actions",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column(
            "alert_id",
            sa.BigInteger(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "decision_id",
            sa.BigInteger(),
            sa.ForeignKey("agent_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "action_type",
            sa.Enum(*_ACTION_TYPE, name="response_action_type_enum", native_enum=False, length=30),
            nullable=False,
        ),
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "status",
            sa.Enum(*_ACTION_STATUS, name="response_status_enum", native_enum=False, length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("approved_by", sa.String(length=80), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Ethics guardrail enforced at the database layer.
        sa.CheckConstraint("simulated = TRUE", name="ck_response_actions_simulated_only"),
    )
    op.create_index(
        "ix_response_actions_alert_id_created_at",
        "response_actions",
        ["alert_id", "created_at"],
    )
    op.create_index(
        "ix_response_actions_status_created_at",
        "response_actions",
        ["status", "created_at"],
    )
    op.create_index("ix_response_actions_action_type", "response_actions", ["action_type"])

    op.create_table(
        "incident_reports",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column(
            "kind",
            sa.Enum(*_INCIDENT_KIND, name="incident_kind_enum", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column(
            "alert_id",
            sa.BigInteger(),
            sa.ForeignKey("alerts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("md_path", sa.Text(), nullable=True),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_incident_reports_kind_created_at",
        "incident_reports",
        ["kind", "created_at"],
    )
    op.create_index("ix_incident_reports_alert_id", "incident_reports", ["alert_id"])
    op.create_index(
        "ix_incident_reports_period_start", "incident_reports", ["period_start"]
    )


def downgrade() -> None:
    # Reverse FK order: drop dependents before parents.
    op.drop_table("incident_reports")
    op.drop_table("response_actions")
    op.drop_table("agent_decisions")
    op.drop_table("alert_artifacts")
    op.drop_table("alerts")
    op.drop_table("network_events")
    op.drop_table("model_versions")
    op.drop_table("ingestion_jobs")
