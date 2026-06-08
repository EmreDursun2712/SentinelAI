"""Pydantic DTOs for authentication and user management."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Role


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    """Full user record (admin views, /auth/me when DB-backed)."""

    id: int
    username: str
    role: Role
    is_active: bool
    token_version: int
    failed_login_count: int
    locked_until: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MeOut(BaseModel):
    """Lightweight identity derived from the JWT (no DB lookup)."""

    username: str
    role: Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: MeOut


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=200)
    role: Role = Role.VIEWER
