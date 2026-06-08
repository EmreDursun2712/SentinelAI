"""Password hashing, API-key, JWT, and refresh-token helpers.

Access tokens are short-lived signed JWTs carrying ``sub`` (username), ``role``,
and ``ver`` (the user's token version); ``decode_access_token`` validates the
signature and expiry. Long-lived **refresh tokens** are opaque random strings —
only their SHA-256 hash is stored (see ``hash_refresh_token``), so a database
leak never exposes a usable token. Passwords are bcrypt-hashed via passlib; the
plaintext is never stored or logged.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

# bcrypt with passlib's recommended defaults. ``deprecated="auto"`` lets us
# rotate to a stronger scheme later without invalidating existing hashes.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """Return a bcrypt hash for ``password``."""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Constant-time check of ``plain_password`` against a stored bcrypt hash."""
    try:
        return _pwd_context.verify(plain_password, password_hash)
    except ValueError:
        # Malformed/empty hash — treat as a failed verification, never raise.
        return False


def access_token_ttl() -> timedelta:
    return timedelta(minutes=get_settings().access_token_ttl_minutes)


def refresh_token_ttl() -> timedelta:
    return timedelta(days=get_settings().refresh_token_ttl_days)


def generate_refresh_token() -> str:
    """Return a fresh, URL-safe opaque refresh token (≈256 bits of entropy)."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Return the SHA-256 hex digest stored for ``token``.

    Refresh tokens are high-entropy randoms (not passwords), so a fast,
    deterministic hash is the right tool: it lets us look the token up by hash
    while never persisting the value itself. Constant-time compare on lookup.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    subject: str, extra_claims: dict[str, Any] | None = None
) -> tuple[str, datetime]:
    """Mint a signed JWT. Returns ``(token, expires_at)``.

    ``expires_at`` is a timezone-aware UTC datetime so callers can surface it to
    the client without re-deriving it from the TTL.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + access_token_ttl()
    claims: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if extra_claims:
        claims.update(extra_claims)
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def verify_api_key(candidate: str | None) -> bool:
    return bool(candidate) and candidate == get_settings().api_key
