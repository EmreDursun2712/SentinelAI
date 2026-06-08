"""Password policy unit tests (pure, no DB)."""

from __future__ import annotations

import pytest

from app.core.errors import WeakPasswordError
from app.core.password_policy import password_issues, validate_password


def test_strong_password_has_no_issues() -> None:
    assert password_issues("Str0ng-Passw0rd!", username="alice") == []


def test_rejects_too_short() -> None:
    issues = password_issues("Ab1!xyz")  # 7 chars
    assert any("12 characters" in i for i in issues)


def test_requires_three_categories() -> None:
    # 16 lowercase letters: long enough, but only one category.
    issues = password_issues("abcdefghijklmnop")
    assert any("3 of" in i for i in issues)
    # lowercase + digit + symbol = 3 categories → OK
    assert password_issues("abcdefgh-123") == []


def test_rejects_username_substring() -> None:
    issues = password_issues("Alice-Secret-12", username="alice")
    assert any("username" in i for i in issues)


def test_validate_password_raises_with_issue_list() -> None:
    with pytest.raises(WeakPasswordError) as exc:
        validate_password("short", username="bob")
    assert exc.value.code == "weak_password"
    assert exc.value.details is not None
    assert isinstance(exc.value.details["issues"], list)
    assert exc.value.details["issues"]


def test_validate_password_passes_silently_when_strong() -> None:
    # Should not raise.
    validate_password("Another-G00d-Pass", username="carol")
