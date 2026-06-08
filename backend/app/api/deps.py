"""Shared FastAPI dependencies: DB session and JWT authentication / RBAC.

Two layers:

* ``get_current_user`` — validates the access token (Bearer header, or an access
  cookie as a fallback) and builds an :class:`AuthPrincipal` from its claims, no
  DB hit. Used for cheap identity (rate-limit keying, WebSocket auth).
* ``get_active_principal`` — additionally loads the user and enforces
  ``is_active`` **and** ``token_version`` on every protected request. This is
  what every functional router depends on (via ``enforce_rbac``), so a
  deactivated user — or one logged out everywhere — loses access immediately,
  not at token expiry.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import ACCESS_COOKIE
from app.core.db import get_session
from app.core.errors import ForbiddenError, RateLimitedError, UnauthorizedError
from app.core.logging import get_logger
from app.core.ratelimit import get_policy, get_rate_limiter
from app.core.security import decode_access_token, verify_api_key
from app.models.enums import Role, role_satisfies
from app.services import user_service

logger = get_logger(__name__)


async def db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(db_session)]


# HTTP methods that only read state. Everything else is a mutation.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class AuthPrincipal:
    """The authenticated caller, reconstructed from validated JWT claims."""

    username: str
    role: Role
    # ``ver`` claim — the user's token_version when the token was minted. None for
    # tokens that predate the field; checked against the live value when present.
    token_version: int | None = None


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    access_cookie: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> AuthPrincipal:
    """Validate the access token and return the caller (claims only, no DB).

    The token is read from the ``Authorization: Bearer <jwt>`` header, falling
    back to the ``sentinelai_access`` cookie. Raises 401 for a missing,
    malformed, expired, or wrongly-signed token, or an unknown ``role`` claim.
    """
    token = _bearer_token(authorization)
    if token is None and access_cookie and access_cookie.strip():
        token = access_cookie.strip()
    if token is None:
        raise UnauthorizedError("Missing or malformed access token.")

    claims = decode_access_token(token)
    if claims is None:
        raise UnauthorizedError("Invalid or expired access token.")

    username = claims.get("sub")
    role_raw = claims.get("role")
    if not username or not role_raw:
        raise UnauthorizedError("Token is missing required claims.")
    try:
        role = Role(role_raw)
    except ValueError as exc:
        raise UnauthorizedError("Token carries an unknown role.") from exc

    ver = claims.get("ver")
    return AuthPrincipal(
        username=str(username),
        role=role,
        token_version=int(ver) if isinstance(ver, int) else None,
    )


CurrentUser = Annotated[AuthPrincipal, Depends(get_current_user)]


async def get_active_principal(principal: CurrentUser, session: SessionDep) -> AuthPrincipal:
    """Enforce ``is_active`` + ``token_version`` against the DB for ``principal``.

    Raises 401 if the account is missing/deactivated, or if the token's ``ver``
    no longer matches the live ``token_version`` (i.e. logged out everywhere).
    Returns a principal whose role reflects the **current** DB role.
    """
    user = await user_service.get_active_user(session, principal.username)
    if user is None:
        raise UnauthorizedError("Account is inactive or no longer exists.")
    if principal.token_version is not None and principal.token_version != user.token_version:
        raise UnauthorizedError("Token has been revoked. Please sign in again.")
    return AuthPrincipal(username=user.username, role=user.role, token_version=user.token_version)


ActiveUser = Annotated[AuthPrincipal, Depends(get_active_principal)]


def require_roles(*roles: Role):
    """Dependency factory: allow only callers whose role is in ``roles``.

    Use the rank-aware ``require_min_role`` for "at least X" policies; this exact
    membership form is handy for admin-only or analyst-only endpoints.
    """
    allowed = frozenset(roles)

    async def _dep(user: CurrentUser) -> AuthPrincipal:
        if user.role not in allowed:
            raise ForbiddenError(
                "Your role is not permitted to perform this action.",
                details={
                    "required": [r.value for r in roles],
                    "actual": user.role.value,
                },
            )
        return user

    return _dep


def require_min_role(minimum: Role):
    """Dependency factory: allow callers whose role is at least ``minimum``."""

    async def _dep(user: CurrentUser) -> AuthPrincipal:
        if not role_satisfies(user.role, minimum):
            raise ForbiddenError(
                "Your role does not have sufficient privilege.",
                details={"required_min": minimum.value, "actual": user.role.value},
            )
        return user

    return _dep


# Convenience role guards for per-endpoint use.
require_admin = require_roles(Role.ADMIN)
require_analyst = require_min_role(Role.ANALYST)
require_viewer = require_min_role(Role.VIEWER)


async def enforce_rbac(request: Request, user: ActiveUser) -> AuthPrincipal:
    """Method-based RBAC applied to every protected ``/api/v1`` router.

    Depends on ``get_active_principal``, so every protected request also
    re-checks ``is_active`` + ``token_version`` against the DB. Read requests
    (GET/HEAD/OPTIONS) require VIEWER+; any mutation requires ANALYST+. ADMIN
    satisfies both. Endpoints needing stricter rules add their own ``require_*``.
    """
    minimum = Role.VIEWER if request.method in _SAFE_METHODS else Role.ANALYST
    if not role_satisfies(user.role, minimum):
        raise ForbiddenError(
            "Your role is not permitted to perform this action.",
            details={"required_min": minimum.value, "actual": user.role.value},
        )
    return user


async def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Service-to-service guard kept for non-interactive callers."""
    if not verify_api_key(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


# ---------------------------------------------------------------------------
# Rate limiting.
# ---------------------------------------------------------------------------


async def get_optional_user(
    authorization: Annotated[str | None, Header()] = None,
) -> AuthPrincipal | None:
    """Like ``get_current_user`` but returns None instead of raising 401.

    Lets the rate-limit dependency key authenticated callers by user and fall
    back to the client IP for unauthenticated ones (e.g. the login endpoint).
    """
    try:
        return await get_current_user(authorization)
    except UnauthorizedError:
        return None


OptionalUser = Annotated["AuthPrincipal | None", Depends(get_optional_user)]


def client_ip(request: Request) -> str:
    """Best-effort client IP. Honors the first X-Forwarded-For hop behind a proxy."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_identity(principal: AuthPrincipal | None, ip: str) -> str:
    """Bucket identity: the user when authenticated, else the client IP."""
    return f"user:{principal.username}" if principal is not None else f"ip:{ip}"


async def enforce_rate_limit(request: Request, policy_name: str, identity: str) -> None:
    """Consume one token from ``policy_name`` for ``identity``; raise 429 if empty."""
    policy = get_policy(policy_name)
    key = f"rl:{policy_name}:{identity}"
    result = await get_rate_limiter().hit(key, policy)
    if not result.allowed:
        logger.warning(
            "ratelimit.exceeded",
            policy=policy_name,
            identity=identity,
            request_id=getattr(request.state, "request_id", None),
            retry_after=result.retry_after,
        )
        raise RateLimitedError(retry_after=result.retry_after)


def rate_limit(policy_name: str):
    """Dependency factory enforcing ``policy_name`` keyed by user (or IP).

    Use for authenticated endpoints. The login endpoint applies its own
    IP+username limit in-handler, where the username is available.
    """

    async def _dep(request: Request, principal: OptionalUser) -> None:
        identity = rate_limit_identity(principal, client_ip(request))
        await enforce_rate_limit(request, policy_name, identity)

    return _dep
