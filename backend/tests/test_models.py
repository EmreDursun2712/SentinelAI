"""Static checks on the ORM metadata. No database connection required."""

from __future__ import annotations

from app.core.db import Base

EXPECTED_TABLES = {
    "ingestion_jobs",
    "model_versions",
    "network_events",
    "alerts",
    "alert_artifacts",
    "agent_decisions",
    "response_actions",
    "incident_reports",
}


def test_expected_tables_register_with_metadata() -> None:
    import app.models  # noqa: F401 — triggers model registration

    table_names = set(Base.metadata.tables.keys())
    missing = EXPECTED_TABLES - table_names
    assert not missing, f"Missing tables: {missing}"


def test_alerts_has_indexes_for_dashboard_queries() -> None:
    import app.models  # noqa: F401

    alerts = Base.metadata.tables["alerts"]
    index_names = {idx.name for idx in alerts.indexes}
    for required in (
        "ix_alerts_status_created_at",
        "ix_alerts_severity_created_at",
        "ix_alerts_src_ip",
        "ix_alerts_dst_ip",
        "ix_alerts_created_at",
    ):
        assert required in index_names, f"Missing index {required!r} on alerts"


def test_response_actions_enforces_simulated_unless_lab() -> None:
    import app.models  # noqa: F401

    actions = Base.metadata.tables["response_actions"]
    check_names = {c.name for c in actions.constraints if c.name}
    # The guardrail is now mode-aware: non-simulated only allowed in LAB mode.
    assert "ck_response_actions_simulated_unless_lab" in check_names
    assert "ck_response_actions_simulated_only" not in check_names


def test_alerts_confidence_check_constraint_present() -> None:
    import app.models  # noqa: F401

    alerts = Base.metadata.tables["alerts"]
    check_names = {c.name for c in alerts.constraints if c.name}
    assert "ck_alerts_confidence_range" in check_names


def test_model_versions_has_partial_unique_index() -> None:
    import app.models  # noqa: F401

    model_versions = Base.metadata.tables["model_versions"]
    matches = [idx for idx in model_versions.indexes if idx.name == "uq_model_versions_one_active"]
    assert matches, "Partial unique index for is_active is missing"
    assert matches[0].unique
