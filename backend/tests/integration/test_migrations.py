"""Migration integration tests — run the real Alembic chain on a real Postgres.

Covers:
* ``upgrade head`` on a pristine, empty database.
* a full ``downgrade base`` → ``upgrade head`` round-trip (surfaces a broken
  downgrade with a clear failure).
* a single-step ``downgrade -1`` → ``upgrade head`` cycle.
* the migration head matches the ORM model metadata (catches table/column drift
  between models and migrations before it bites at runtime).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  (register every model on Base.metadata)
from app.core.db import Base

from .conftest import alembic_config, alembic_downgrade, alembic_upgrade, settings_database_url

pytestmark = pytest.mark.integration

# Tables the schema must contain once migrated to head. (Sanity set, not
# exhaustive — drift is checked structurally below.)
EXPECTED_TABLES = {
    "alembic_version",
    "users",
    "auth_sessions",
    "ingestion_jobs",
    "network_events",
    "model_versions",
    "alerts",
    "agent_decisions",
    "response_actions",
    "alert_artifacts",
    "incident_reports",
    "model_drift_snapshots",
}

# compare_metadata ops that signal real schema drift we always want to fail on.
SIGNIFICANT_OPS = {"add_table", "remove_table", "add_column", "remove_column"}


def _sync_engine(url: str):
    return create_engine(make_url(url), poolclass=NullPool)


def _current_revision(url: str) -> str | None:
    from alembic.migration import MigrationContext

    engine = _sync_engine(url)
    with engine.connect() as conn:
        rev = MigrationContext.configure(conn).get_current_revision()
    engine.dispose()
    return rev


def _script_head() -> str:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def test_upgrade_head_on_empty_database(fresh_db_url: str) -> None:
    """`alembic upgrade head` on a clean DB builds the whole schema and stamps head."""
    alembic_upgrade(fresh_db_url, "head")

    engine = _sync_engine(fresh_db_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    missing = EXPECTED_TABLES - tables
    assert not missing, f"migrations did not create: {sorted(missing)}"
    assert _current_revision(fresh_db_url) == _script_head()


def test_full_downgrade_then_upgrade_roundtrip(fresh_db_url: str) -> None:
    """head → base → head. A broken downgrade in any revision fails loudly here."""
    alembic_upgrade(fresh_db_url, "head")

    try:
        alembic_downgrade(fresh_db_url, "base")
    except Exception as exc:  # we want the clearest possible signal on a bad downgrade
        pytest.fail(f"downgrade to base failed (a revision's downgrade() is broken): {exc!r}")

    # Back to empty: no app tables, only an (empty) alembic_version may remain.
    engine = _sync_engine(fresh_db_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    leftover = tables - {"alembic_version"}
    assert not leftover, f"downgrade base left tables behind: {sorted(leftover)}"
    assert _current_revision(fresh_db_url) is None

    # And it must come straight back up.
    alembic_upgrade(fresh_db_url, "head")
    assert _current_revision(fresh_db_url) == _script_head()


def test_single_step_downgrade_upgrade_cycle(fresh_db_url: str) -> None:
    """head → -1 → head: the most recent migration is reversible."""
    alembic_upgrade(fresh_db_url, "head")
    head = _script_head()

    alembic_downgrade(fresh_db_url, "-1")
    assert _current_revision(fresh_db_url) != head  # actually stepped back

    alembic_upgrade(fresh_db_url, "head")
    assert _current_revision(fresh_db_url) == head


def test_migration_head_matches_model_metadata(fresh_db_url: str) -> None:
    """Autogenerate finds no table/column drift between models and migrations.

    Index / constraint / server-default nuances (partial indexes, expression
    indexes like ``priority DESC``) are noisy under autogenerate, so the hard
    assertion is scoped to table + column presence — the drift that actually
    breaks queries at runtime. Any such diff is reported in full.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    alembic_upgrade(fresh_db_url, "head")

    engine = _sync_engine(fresh_db_url)
    with engine.connect() as conn:
        mc = MigrationContext.configure(
            conn,
            opts={"compare_type": True, "compare_server_default": True},
        )
        # env.py target metadata is Base.metadata; mirror that here.
        with settings_database_url(fresh_db_url):
            raw_diffs = compare_metadata(mc, Base.metadata)
    engine.dispose()

    # compare_metadata mixes single tuples with grouped lists; flatten one level.
    flat: list[tuple] = []
    for d in raw_diffs:
        if isinstance(d, list):
            flat.extend(d)
        else:
            flat.append(d)

    significant = [
        d for d in flat if d and d[0] in SIGNIFICANT_OPS and "alembic_version" not in repr(d)
    ]
    assert not significant, "model/migration drift (tables/columns):\n" + "\n".join(
        repr(d) for d in significant
    )


def test_alembic_version_table_present_at_head(fresh_db_url: str) -> None:
    """The version table exists and holds exactly the head revision after upgrade."""
    alembic_upgrade(fresh_db_url, "head")
    engine = _sync_engine(fresh_db_url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    engine.dispose()
    assert rows == [_script_head()]
