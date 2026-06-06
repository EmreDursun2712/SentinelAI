"""User management + authentication service.

The only place that reads or writes the ``users`` table. Per-request auth is
stateless (token claims), so these functions run at login, at bootstrap, and
through the admin user-management endpoint — never on the hot path.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.core.logging import get_logger
from app.core.security import get_password_hash, verify_password
from app.models import User
from app.models.enums import Role

logger = get_logger(__name__)


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


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
    if await get_user_by_username(session, username) is not None:
        raise ConflictError(
            f"User '{username}' already exists.", details={"username": username}
        )

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


async def authenticate(
    session: AsyncSession, *, username: str, password: str
) -> User | None:
    """Return the user if credentials are valid and the account is active.

    Returns ``None`` for unknown user, wrong password, or deactivated account.
    The branches are intentionally indistinguishable to the caller so the API
    cannot be used to enumerate valid usernames.
    """
    user = await get_user_by_username(session, username.strip())
    if user is None:
        # Hash a throwaway value so response timing doesn't leak whether the
        # username exists (mitigates user enumeration via timing).
        verify_password(password, _DUMMY_HASH)
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
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
    user = await create_user(
        session, username=username, password=password, role=Role.ADMIN
    )
    logger.info("user.bootstrap_admin_created", username=username)
    return user


# Precomputed bcrypt hash of a random string, used only for timing-equalization
# in ``authenticate`` when the username is unknown.
_DUMMY_HASH = get_password_hash("sentinelai-timing-equalizer")
