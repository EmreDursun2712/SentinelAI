"""Integration-test infrastructure: a throwaway Postgres + per-test isolation.

These tests exercise the *real* database — migrations, CHECK/FK/unique
constraints, JSONB, and the committing service transactions — using a disposable
PostgreSQL container (testcontainers). They need Docker.

They are excluded from the default `pytest` run (see ``addopts`` /
``-m 'not integration'`` in pyproject) and opt-in with ``pytest -m integration``.
Each integration module declares ``pytestmark = pytest.mark.integration`` so the
marker is present at collection time and the filter is deterministic.

Everything here degrades to a clean *skip* when testcontainers is missing or
Docker is unreachable, so the fast unit suite never breaks because of this layer.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

# tests/integration/conftest.py -> parents[2] == backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
PG_IMAGE = os.environ.get("SENTINELAI_TEST_PG_IMAGE", "postgres:16-alpine")


# ---------------------------------------------------------------------------
# Container + URL (session-scoped, synchronous — no event loop involved).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Start a disposable Postgres for the whole integration session.

    Yields a ``postgresql+psycopg://`` URL usable by both the async app engine
    and Alembic (psycopg3 drives sync *and* async). Skips cleanly if Docker or
    testcontainers is unavailable so the suite never hard-fails on environment.
    """
    postgres = pytest.importorskip("testcontainers.postgres")
    try:
        container = postgres.PostgresContainer(PG_IMAGE, driver="psycopg")
        container.start()
    except Exception as exc:  # docker down, image pull blocked, etc.
        pytest.skip(f"Postgres testcontainer unavailable: {exc}")

    try:
        url = make_url(container.get_connection_url()).render_as_string(hide_password=False)
        yield url
    finally:
        with contextlib.suppress(Exception):
            container.stop()


# ---------------------------------------------------------------------------
# Alembic helpers — drive migrations against an arbitrary URL.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def settings_database_url(url: str) -> Iterator[None]:
    """Point app settings (and thus Alembic's ``env.py``) at ``url`` temporarily."""
    from app.core.config import get_settings

    previous = os.environ.get("SENTINEL_DATABASE_URL")
    os.environ["SENTINEL_DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SENTINEL_DATABASE_URL", None)
        else:
            os.environ["SENTINEL_DATABASE_URL"] = previous
        get_settings.cache_clear()


def alembic_config():
    """Alembic ``Config`` pinned to this project's migrations, path-independent."""
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def alembic_upgrade(url: str, revision: str = "head") -> None:
    from alembic import command

    with settings_database_url(url):
        command.upgrade(alembic_config(), revision)


def alembic_downgrade(url: str, revision: str) -> None:
    from alembic import command

    with settings_database_url(url):
        command.downgrade(alembic_config(), revision)


# ---------------------------------------------------------------------------
# Schema fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def migrated_url(postgres_url: str) -> str:
    """The session Postgres with the full migration chain applied to head.

    Building the shared schema *through Alembic* means the constraint/query
    tests run against exactly the DDL migrations produce — not a separate
    ``create_all`` — so a migration that forgets a constraint is caught here too.
    """
    alembic_upgrade(postgres_url, "head")
    return postgres_url


@pytest.fixture
async def db_session(migrated_url: str) -> AsyncIterator[AsyncSession]:
    """An ``AsyncSession`` whose work is rolled back after each test.

    Binds to a single connection holding an outer transaction; the session
    joins it via SAVEPOINTs (``join_transaction_mode="create_savepoint"``), so
    service code can call ``commit()`` freely and everything still rolls back at
    teardown. Tests stay isolated without truncating tables between runs.
    """
    engine = create_async_engine(migrated_url, poolclass=NullPool)
    conn = await engine.connect()
    outer = await conn.begin()
    session = AsyncSession(
        bind=conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        if outer.is_active:
            await outer.rollback()
        await conn.close()
        await engine.dispose()


@pytest.fixture
def fresh_db_url(postgres_url: str) -> Iterator[str]:
    """Create + drop a brand-new empty database for a single migration test.

    Gives migration tests a guaranteed-clean target without disturbing the
    shared (already-migrated) database the other tests use.
    """
    base = make_url(postgres_url)
    db_name = f"migr_{uuid.uuid4().hex[:12]}"
    admin = create_engine(
        base.set(database="postgres"),
        isolation_level="AUTOCOMMIT",  # CREATE/DROP DATABASE can't run in a txn
        poolclass=NullPool,
    )
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{db_name}"'))
    try:
        yield base.set(database=db_name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            # Boot any lingering connections so DROP can't be blocked.
            c.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": db_name},
            )
            c.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin.dispose()
