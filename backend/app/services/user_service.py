"""User management + authentication service.

The only place that reads or writes the ``users`` table. Per-request auth is
stateless (token claims), so these functions run at login, at bootstrap, and
through the admin user-management endpoint — never on the hot path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError
from app.core.logging import get_logger
from app.core.password_policy import validate_password
from app.core.security import get_password_hash, verify_password
from app.models import User
from app.models.enums import Role
from app.services import session_service

logger = get_logger(__name__)


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_active_user(session: AsyncSession, username: str) -> User | None:
    """Return the user only if it exists and is active; else ``None``.

    Used on the protected hot path to enforce ``is_active`` on every request, so
    a deactivated account loses access immediately rather than at token expiry.
    """
    user = await get_user_by_username(session, username.strip())
    if user is None or not user.is_active:
        return None
    return user


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role: Role = Role.VIEWER,
    is_active: bool = True,
    commit: bool = True,
) -> User:
    """Create a user with a bcrypt-hashed password.

    Raises ``ConflictError`` if the username already exists.
    """
    username = username.strip()
    if not username:
        raise ConflictError("Username must not be empty.")
    # Enforce the password policy for every created account (admin + bootstrap).
    validate_password(password, username=username)
    if await get_user_by_username(session, username) is not None:
        raise ConflictError(f"User '{username}' already exists.", details={"username": username})

    user = User(
        username=username,
        password_hash=get_password_hash(password),
        role=role,
        is_active=is_active,
    )
    session.add(user)
    if commit:
        await session.commit()
        await session.refresh(user)
    else:
        await session.flush()
    logger.info("user.created", username=username, role=role.value)
    return user


LoginOutcome = Literal["ok", "invalid_credentials", "inactive", "locked"]


@dataclass
class LoginResult:
    """Result of a login attempt. ``retry_after`` is set only when ``locked``."""

    user: User | None
    outcome: LoginOutcome
    retry_after: int | None = None


def is_account_locked(user: User, now: datetime) -> bool:
    return user.locked_until is not None and now < user.locked_until


def seconds_until_unlock(user: User, now: datetime) -> int:
    if user.locked_until is None:
        return 0
    return max(1, int((user.locked_until - now).total_seconds()))


async def _record_failed_login(
    session: AsyncSession, user: User, now: datetime, settings: Settings
) -> bool:
    """Increment the failure counter; lock the account if the threshold is hit.

    The counter resets when the previous failure is older than the window, so it
    measures "N failures within the window". Returns True if this call locked it.
    """
    window = timedelta(minutes=settings.login_failed_window_minutes)
    if user.last_failed_login_at is None or (now - user.last_failed_login_at) > window:
        user.failed_login_count = 1
    else:
        user.failed_login_count += 1
    user.last_failed_login_at = now

    locked = False
    if user.failed_login_count >= settings.login_max_failed_attempts:
        user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
        locked = True
        logger.warning(
            "auth.account_locked",
            username=user.username,
            failed_count=user.failed_login_count,
            locked_until=user.locked_until.isoformat(),
        )
    await session.commit()
    return locked


async def _record_successful_login(session: AsyncSession, user: User) -> None:
    """Clear failure/lock state after a good login (only writes if needed)."""
    if user.failed_login_count or user.last_failed_login_at or user.locked_until:
        user.failed_login_count = 0
        user.last_failed_login_at = None
        user.locked_until = None
        await session.commit()


async def authenticate_login(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> LoginResult:
    """Validate credentials with brute-force lockout.

    Order: unknown user (generic), inactive (generic), already-locked (423),
    wrong password (records a failure — which may lock — generic), success
    (clears counters). Unknown/wrong-password branches stay indistinguishable to
    avoid username enumeration; only an *existing, already-locked* account
    surfaces the lock so the legitimate owner gets a clear message.
    """
    settings = settings or get_settings()
    now = now or datetime.now(UTC)

    user = await get_user_by_username(session, username.strip())
    if user is None:
        # Equalize timing so a missing username can't be detected by latency.
        verify_password(password, _DUMMY_HASH)
        return LoginResult(None, "invalid_credentials")
    if not user.is_active:
        return LoginResult(user, "inactive")
    if is_account_locked(user, now):
        return LoginResult(user, "locked", seconds_until_unlock(user, now))
    if not verify_password(password, user.password_hash):
        await _record_failed_login(session, user, now, settings)
        # Note: even if this attempt crossed the threshold, return a generic
        # failure now; the *next* attempt sees the lock. This avoids leaking the
        # exact attempt that locked the account.
        return LoginResult(user, "invalid_credentials")

    await _record_successful_login(session, user)
    return LoginResult(user, "ok")


async def unlock_user(session: AsyncSession, username: str) -> User | None:
    """Admin reset: clear lockout + failure counters. ``None`` if no such user."""
    user = await get_user_by_username(session, username.strip())
    if user is None:
        return None
    user.failed_login_count = 0
    user.last_failed_login_at = None
    user.locked_until = None
    await session.commit()
    await session.refresh(user)
    logger.info("auth.account_unlocked", username=user.username)
    return user


async def deactivate_user(session: AsyncSession, username: str) -> User | None:
    """Deactivate ``username`` and lock them out immediately.

    Sets ``is_active=False``, bumps ``token_version`` (invalidating every
    outstanding access token), and revokes all refresh sessions. Returns the
    user, or ``None`` if no such user. Idempotent.
    """
    user = await get_user_by_username(session, username.strip())
    if user is None:
        return None
    user.is_active = False
    user.token_version += 1
    await session_service.revoke_all_for_user(session, user.id)
    await session.commit()
    await session.refresh(user)
    logger.info("user.deactivated", username=user.username)
    return user


async def ensure_bootstrap_admin(
    session: AsyncSession, *, username: str, password: str
) -> User | None:
    """Idempotently ensure an ADMIN user exists for ``username``.

    Returns the newly created user, or ``None`` if one already existed (the
    existing user's password is never overwritten — bootstrap is create-only).
    """
    existing = await get_user_by_username(session, username.strip())
    if existing is not None:
        return None
    user = await create_user(session, username=username, password=password, role=Role.ADMIN)
    logger.info("user.bootstrap_admin_created", username=username)
    return user


# Precomputed bcrypt hash of a random string, used only for timing-equalization
# in ``authenticate`` when the username is unknown.
_DUMMY_HASH = get_password_hash("sentinelai-timing-equalizer")
