"""Refresh-token session lifecycle: issue, validate+rotate, and revoke.

The only module that reads/writes ``auth_sessions``. Refresh tokens are opaque
randoms; we persist only their SHA-256 hash. Validation is constant-time by
hash lookup. Rotation revokes the presented token and issues a fresh one, and a
*reuse* of an already-revoked token revokes the user's whole session family
(a strong signal the token leaked).

These helpers ``flush`` but never ``commit`` — the calling endpoint owns the
transaction so cookie issuance and DB state commit together.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import (
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_ttl,
)
from app.models import AuthSession, User

logger = get_logger(__name__)


@dataclass
class IssuedSession:
    raw_token: str
    session: AuthSession


@dataclass
class RotatedSession:
    raw_token: str
    user: User
    session: AuthSession


async def create_session(
    db: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
) -> IssuedSession:
    """Mint a refresh token and persist its hashed session row for ``user``."""
    raw = generate_refresh_token()
    now = datetime.now(UTC)
    row = AuthSession(
        user_id=user.id,
        token_hash=hash_refresh_token(raw),
        expires_at=now + refresh_token_ttl(),
        last_used_at=now,
        user_agent=(user_agent or None),
        ip=(ip or None),
    )
    db.add(row)
    await db.flush()
    logger.info("auth.session_created", user_id=user.id, session_id=row.id)
    return IssuedSession(raw_token=raw, session=row)


async def _get_by_raw(db: AsyncSession, raw_token: str) -> AuthSession | None:
    token_hash = hash_refresh_token(raw_token)
    result = await db.execute(select(AuthSession).where(AuthSession.token_hash == token_hash))
    return result.scalar_one_or_none()


async def rotate_session(
    db: AsyncSession,
    raw_token: str,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
) -> RotatedSession | None:
    """Validate ``raw_token`` and rotate it. Returns ``None`` if not usable.

    Rejects unknown, expired, or revoked tokens and tokens of inactive users.
    A presented-but-already-revoked token is treated as reuse: every session for
    that user is revoked and ``None`` is returned (forces a fresh login).
    """
    row = await _get_by_raw(db, raw_token)
    if row is None:
        return None

    now = datetime.now(UTC)

    if row.revoked_at is not None:
        # Reuse of a rotated/revoked token — revoke the whole family defensively.
        logger.warning("auth.refresh_reuse_detected", user_id=row.user_id, session_id=row.id)
        await revoke_all_for_user(db, row.user_id)
        return None

    if row.expires_at <= now:
        return None

    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None

    # Rotate: revoke the presented session, issue a fresh one.
    row.revoked_at = now
    row.last_used_at = now
    issued = await create_session(db, user, user_agent=user_agent, ip=ip)
    logger.info("auth.session_rotated", user_id=user.id, old=row.id, new=issued.session.id)
    return RotatedSession(raw_token=issued.raw_token, user=user, session=issued.session)


async def revoke_session(db: AsyncSession, raw_token: str) -> bool:
    """Revoke the session for ``raw_token`` if it exists and is still active."""
    row = await _get_by_raw(db, raw_token)
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(UTC)
    await db.flush()
    logger.info("auth.session_revoked", user_id=row.user_id, session_id=row.id)
    return True


async def revoke_all_for_user(db: AsyncSession, user_id: int) -> int:
    """Revoke every still-active session for ``user_id``. Returns the count."""
    now = datetime.now(UTC)
    result = await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.flush()
    count = int(result.rowcount or 0)
    logger.info("auth.sessions_revoked_all", user_id=user_id, count=count)
    return count


async def active_session_count(db: AsyncSession, user_id: int) -> int:
    """Count of non-revoked, non-expired sessions (handy for tests / a UI)."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )
    return len(result.scalars().all())
