"""Authentication API.

Surface:

    POST /api/v1/auth/login    — exchange username/password for a JWT
    GET  /api/v1/auth/me       — current identity (from the token; no DB hit)
    POST /api/v1/auth/logout   — stateless no-op (client discards the token)
    POST /api/v1/auth/users    — create a user (ADMIN only)

Login is the only public endpoint here; the rest require a valid token, and
``/users`` additionally requires the ADMIN role.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import (
    CurrentUser,
    SessionDep,
    client_ip,
    enforce_rate_limit,
    require_admin,
)
from app.core.errors import UnauthorizedError
from app.core.logging import get_logger
from app.core.security import create_access_token
from app.schemas.auth import (
    CreateUserRequest,
    LoginRequest,
    MeOut,
    TokenResponse,
    UserOut,
)
from app.services import user_service

router = APIRouter(prefix="/auth")
logger = get_logger(__name__)


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(
    http_request: Request, session: SessionDep, request: LoginRequest
) -> TokenResponse:
    # Brute-force guard: limit by IP + username together, before touching the DB.
    # This throttles both password-spraying one account and many-account attempts
    # from a single source.
    identity = f"{client_ip(http_request)}:{request.username.strip().lower()}"
    await enforce_rate_limit(http_request, "login", identity)

    user = await user_service.authenticate(
        session, username=request.username, password=request.password
    )
    if user is None:
        # Single generic message — never reveal which half of the pair was wrong.
        raise UnauthorizedError("Invalid username or password.")

    token, expires_at = create_access_token(
        subject=user.username, extra_claims={"role": user.role.value}
    )
    logger.info("auth.login_success", username=user.username, role=user.role.value)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_at=expires_at,
        user=MeOut(username=user.username, role=user.role),
    )


@router.get("/me")
async def me(user: CurrentUser) -> MeOut:
    return MeOut(username=user.username, role=user.role)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(user: CurrentUser) -> dict[str, str]:
    """Stateless logout: tokens are not server-tracked, so the client simply
    discards its token. Endpoint exists for symmetry and audit logging."""
    logger.info("auth.logout", username=user.username)
    return {"detail": "Logged out. Discard the access token client-side."}


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_user(
    session: SessionDep,
    request: CreateUserRequest,
    admin: CurrentUser,
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
