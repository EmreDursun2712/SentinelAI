"""Refresh-session integration tests against real Postgres.

Exercises ``session_service`` + ``user_service`` against the real
``auth_sessions`` table: issue, rotate, revoke, expiry, reuse detection, and the
deactivation flow (which must lock a user out immediately).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_refresh_token
from app.models import AuthSession, User
from app.models.enums import Role
from app.services import session_service, user_service

pytestmark = pytest.mark.integration


async def _make_user(db: AsyncSession, username: str = "alice", role: Role = Role.ANALYST) -> User:
    return await user_service.create_user(
        db, username=username, password="pw-12345", role=role, commit=False
    )


async def test_create_session_stores_only_hash(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    issued = await session_service.create_session(db_session, user, user_agent="UA", ip="10.0.0.1")

    row = (
        await db_session.execute(select(AuthSession).where(AuthSession.id == issued.session.id))
    ).scalar_one()
    # The raw token is never persisted; only its SHA-256 hash is.
    assert row.token_hash == hash_refresh_token(issued.raw_token)
    assert row.token_hash != issued.raw_token
    assert row.revoked_at is None
    assert row.user_agent == "UA" and row.ip == "10.0.0.1"
    assert await session_service.active_session_count(db_session, user.id) == 1


async def test_rotate_revokes_old_and_issues_new(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    issued = await session_service.create_session(db_session, user)
    old_id = issued.session.id

    rotated = await session_service.rotate_session(db_session, issued.raw_token)
    assert rotated is not None
    assert rotated.user.id == user.id
    assert rotated.raw_token != issued.raw_token

    old = await db_session.get(AuthSession, old_id)
    assert old is not None and old.revoked_at is not None  # old session revoked
    # Exactly one active session remains (the new one).
    assert await session_service.active_session_count(db_session, user.id) == 1


async def test_rotate_rejects_expired_token(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    issued = await session_service.create_session(db_session, user)
    issued.session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    assert await session_service.rotate_session(db_session, issued.raw_token) is None


async def test_rotate_rejects_inactive_user(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    issued = await session_service.create_session(db_session, user)
    user.is_active = False
    await db_session.flush()

    assert await session_service.rotate_session(db_session, issued.raw_token) is None


async def test_reuse_of_revoked_token_revokes_family(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    issued = await session_service.create_session(db_session, user)

    # First rotation succeeds (old token now revoked).
    rotated = await session_service.rotate_session(db_session, issued.raw_token)
    assert rotated is not None
    assert await session_service.active_session_count(db_session, user.id) == 1

    # Replaying the original (now-revoked) token is treated as theft: the whole
    # family is revoked and the call fails.
    assert await session_service.rotate_session(db_session, issued.raw_token) is None
    assert await session_service.active_session_count(db_session, user.id) == 0


async def test_revoke_session(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    issued = await session_service.create_session(db_session, user)

    assert await session_service.revoke_session(db_session, issued.raw_token) is True
    assert await session_service.active_session_count(db_session, user.id) == 0
    # Revoking again is a no-op.
    assert await session_service.revoke_session(db_session, issued.raw_token) is False


async def test_revoke_all_for_user(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    await session_service.create_session(db_session, user)
    await session_service.create_session(db_session, user)
    await session_service.create_session(db_session, user)

    revoked = await session_service.revoke_all_for_user(db_session, user.id)
    assert revoked == 3
    assert await session_service.active_session_count(db_session, user.id) == 0


async def test_deactivate_user_locks_out_immediately(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "victim")
    issued = await session_service.create_session(db_session, user)
    original_version = user.token_version

    deactivated = await user_service.deactivate_user(db_session, "victim")
    assert deactivated is not None
    assert deactivated.is_active is False
    assert deactivated.token_version == original_version + 1  # invalidates access tokens
    # All refresh sessions revoked → refresh is dead too.
    assert await session_service.active_session_count(db_session, user.id) == 0
    assert await session_service.rotate_session(db_session, issued.raw_token) is None
