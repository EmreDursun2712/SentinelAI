"""Authentication API — cookie + refresh-token auth with revocation.

Surface:

    POST /api/v1/auth/login       — username/password → access token (body)
                                     + httpOnly refresh cookie + CSRF cookie
    POST /api/v1/auth/refresh     — rotate the refresh cookie → new access token
    POST /api/v1/auth/logout      — revoke the current refresh session + clear cookies
    POST /api/v1/auth/logout-all  — revoke every session for the user (all devices)
    GET  /api/v1/auth/me          — current identity (enforces is_active)
    POST /api/v1/auth/users       — create a user (ADMIN)
    POST /api/v1/auth/users/{username}/deactivate — deactivate a user (ADMIN)

The access token is short-lived and returned in the body (the SPA holds it in
memory and sends it as a Bearer). The refresh token is the long-lived secret and
never leaves an httpOnly cookie. ``/refresh`` rotates it; reuse of a rotated
token revokes the whole session family. CSRF (double-submit) is enforced by
middleware on cookie-authenticated mutations — i.e. ``/refresh``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    ActiveUser,
    SessionDep,
    client_ip,
    enforce_rate_limit,
    require_admin,
)
from app.core.config import Settings, get_settings
from app.core.cookies import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    new_csrf_token,
    set_csrf_cookie,
    set_refresh_cookie,
)
from app.core.errors import AccountLockedError, NotFoundError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import create_access_token
from app.models import User
from app.schemas.auth import (
    CreateUserRequest,
    LoginRequest,
    MeOut,
    TokenResponse,
    UserOut,
)
from app.services import session_service, user_service

router = APIRouter(prefix="/auth")
logger = get_logger(__name__)


def _cookie_max_age(settings: Settings) -> int:
    return settings.refresh_token_ttl_days * 24 * 60 * 60


def _issue_tokens(
    response: Response,
    settings: Settings,
    *,
    user: User,
    refresh_token: str,
) -> TokenResponse:
    """Set the refresh + CSRF cookies and build the access-token body."""
    access_token, expires_at = create_access_token(
        subject=user.username,
        extra_claims={"role": user.role.value, "ver": user.token_version},
    )
    max_age = _cookie_max_age(settings)
    set_refresh_cookie(response, settings, refresh_token, max_age=max_age)
    set_csrf_cookie(response, settings, new_csrf_token(), max_age=max_age)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_at=expires_at,
        user=MeOut(username=user.username, role=user.role),
    )


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(
    http_request: Request,
    response: Response,
    session: SessionDep,
    request: LoginRequest,
) -> TokenResponse:
    # Brute-force guard: limit by IP + username together, before touching the DB.
    # This is separate from per-account lockout below (rate limit throttles a
    # source; lockout protects a targeted account).
    identity = f"{client_ip(http_request)}:{request.username.strip().lower()}"
    await enforce_rate_limit(http_request, "login", identity)

    result = await user_service.authenticate_login(
        session, username=request.username, password=request.password
    )
    if result.outcome == "locked":
        raise AccountLockedError(result.retry_after or 0)
    if result.outcome != "ok" or result.user is None:
        # Single generic message — never reveal which half of the pair was wrong.
        raise UnauthorizedError("Invalid username or password.")
    user = result.user

    issued = await session_service.create_session(
        session,
        user,
        user_agent=http_request.headers.get("user-agent"),
        ip=client_ip(http_request),
    )
    body = _issue_tokens(response, get_settings(), user=user, refresh_token=issued.raw_token)
    await session.commit()
    logger.info("auth.login_success", username=user.username, role=user.role.value)
    return body


def _refresh_failure(http_request: Request, settings: Settings) -> JSONResponse:
    """401 envelope that also clears the auth cookies (sent because we *return*,
    not raise — a raised error would discard the Set-Cookie deletions)."""
    failure = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "error": {
                "code": "unauthorized",
                "message": "Refresh token is invalid or expired. Please sign in again.",
                "details": None,
            },
            "request_id": getattr(http_request.state, "request_id", None),
        },
    )
    clear_auth_cookies(failure, settings)
    return failure


@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def refresh(
    http_request: Request,
    response: Response,
    session: SessionDep,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> TokenResponse | JSONResponse:
    """Rotate the refresh cookie and mint a new access token.

    CSRF is enforced upstream by middleware (the request carries the refresh
    cookie). Invalid/expired/revoked tokens clear cookies and return 401.
    """
    settings = get_settings()
    if not refresh_token:
        return _refresh_failure(http_request, settings)

    rotated = await session_service.rotate_session(
        session,
        refresh_token,
        user_agent=http_request.headers.get("user-agent"),
        ip=client_ip(http_request),
    )
    if rotated is None:
        await session.commit()  # persist any reuse-driven revocations
        return _refresh_failure(http_request, settings)

    body = _issue_tokens(response, settings, user=rotated.user, refresh_token=rotated.raw_token)
    await session.commit()
    logger.info("auth.refresh_success", username=rotated.user.username)
    return body


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    response: Response,
    session: SessionDep,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> dict[str, str]:
    """Revoke the current refresh session and clear cookies.

    Requires no valid access token (so an expired session can still log out);
    exempt from CSRF for the same reason. Always succeeds.
    """
    if refresh_token:
        await session_service.revoke_session(session, refresh_token)
        await session.commit()
    clear_auth_cookies(response, get_settings())
    return {"detail": "Logged out."}


@router.post("/logout-all", status_code=status.HTTP_200_OK)
async def logout_all(
    response: Response,
    session: SessionDep,
    user: ActiveUser,
) -> dict[str, str]:
    """Revoke every session for the caller and invalidate all access tokens.

    Bumps ``token_version`` so any still-valid access token is rejected on its
    next protected request (see ``get_active_principal``)."""
    db_user = await user_service.get_user_by_username(session, user.username)
    if db_user is not None:
        db_user.token_version += 1
        await session_service.revoke_all_for_user(session, db_user.id)
        await session.commit()
    clear_auth_cookies(response, get_settings())
    logger.info("auth.logout_all", username=user.username)
    return {"detail": "Logged out of all sessions."}


@router.get("/me")
async def me(user: ActiveUser) -> MeOut:
    return MeOut(username=user.username, role=user.role)


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_user(
    session: SessionDep,
    request: CreateUserRequest,
    admin: ActiveUser,
) -> UserOut:
    user = await user_service.create_user(
        session,
        username=request.username,
        password=request.password,
        role=request.role,
    )
    logger.info(
        "auth.user_created_by_admin",
        created=user.username,
        role=user.role.value,
        by=admin.username,
    )
    return UserOut.model_validate(user)


@router.post(
    "/users/{username}/deactivate",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def deactivate_user(
    session: SessionDep,
    username: str,
    admin: ActiveUser,
) -> UserOut:
    """Deactivate a user: locks login, revokes sessions, invalidates tokens."""
    user = await user_service.deactivate_user(session, username)
    if user is None:
        raise NotFoundError(f"User '{username}' not found.")
    logger.info("auth.user_deactivated_by_admin", target=username, by=admin.username)
    return UserOut.model_validate(user)


@router.post(
    "/users/{username}/unlock",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
)
async def unlock_user(
    session: SessionDep,
    username: str,
    admin: ActiveUser,
) -> UserOut:
    """Admin reset of a locked-out account: clears the failure counter + lock."""
    user = await user_service.unlock_user(session, username)
    if user is None:
        raise NotFoundError(f"User '{username}' not found.")
    logger.info("auth.user_unlocked_by_admin", target=username, by=admin.username)
    return UserOut.model_validate(user)
