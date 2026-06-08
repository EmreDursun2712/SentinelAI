"""Password policy — the single source of truth for password strength rules.

Rules (mirrored client-side in ``frontend/src/lib/auth/passwordPolicy.ts``):

* at least 12 characters,
* at least 3 of 4 character categories: lowercase, uppercase, number, symbol,
* must not contain the username (case-insensitive).

``password_issues`` returns a list of human-readable problems (empty ⇒ valid);
``validate_password`` raises :class:`WeakPasswordError` with that list.
"""

from __future__ import annotations

from app.core.errors import WeakPasswordError

MIN_LENGTH = 12
MIN_CATEGORIES = 3


def _categories(password: str) -> int:
    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)
    # Anything that isn't a letter or digit counts as a symbol (incl. spaces).
    has_symbol = any(not c.isalnum() for c in password)
    return sum((has_lower, has_upper, has_digit, has_symbol))


def password_issues(password: str, *, username: str | None = None) -> list[str]:
    """Return the list of policy violations for ``password`` (empty ⇒ valid)."""
    issues: list[str] = []
    if len(password) < MIN_LENGTH:
        issues.append(f"Must be at least {MIN_LENGTH} characters.")
    if _categories(password) < MIN_CATEGORIES:
        issues.append(
            f"Must include at least {MIN_CATEGORIES} of: lowercase, uppercase, number, symbol."
        )
    if username and username.strip() and username.strip().lower() in password.lower():
        issues.append("Must not contain the username.")
    return issues


def validate_password(password: str, *, username: str | None = None) -> None:
    """Raise :class:`WeakPasswordError` if ``password`` violates the policy."""
    issues = password_issues(password, username=username)
    if issues:
        raise WeakPasswordError(issues)
