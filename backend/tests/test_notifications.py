"""External notification gating + payload logic (no network)."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.notification_service import (
    NotificationPayload,
    dispatch,
    severity_meets_threshold,
    should_notify,
)


def _settings(**over) -> Settings:
    base = {"jwt_secret": "x" * 20, "notifications_enabled": True}
    return Settings(**{**base, **over})


def test_severity_threshold_ordering() -> None:
    assert severity_meets_threshold("CRITICAL", "HIGH")
    assert severity_meets_threshold("HIGH", "HIGH")
    assert not severity_meets_threshold("MEDIUM", "HIGH")
    assert not severity_meets_threshold(None, "LOW")


def test_should_notify_requires_enabled_and_channel() -> None:
    # Enabled but no channel configured → no.
    assert not should_notify(_settings(), "CRITICAL", reason="new_alert")
    # Channel configured + severity clears threshold → yes.
    s = _settings(slack_webhook_url="https://hooks.example/x", notify_min_severity="HIGH")
    assert should_notify(s, "CRITICAL", reason="new_alert")
    assert not should_notify(s, "LOW", reason="new_alert")


def test_disabled_never_notifies() -> None:
    s = _settings(notifications_enabled=False, slack_webhook_url="https://hooks.example/x")
    assert not should_notify(s, "CRITICAL", reason="new_alert")


def test_confirmed_overrides_severity_threshold() -> None:
    s = _settings(slack_webhook_url="https://hooks.example/x", notify_min_severity="CRITICAL")
    # A LOW alert wouldn't clear the threshold, but a CONFIRMED verdict always notifies.
    assert should_notify(s, "LOW", reason="confirmed")


def test_channels_reflect_configuration() -> None:
    s = _settings(
        slack_webhook_url="https://hooks.example/x",
        notify_webhook_url="https://hook.example/y",
        smtp_host="smtp.example",
        smtp_from="soc@example",
        notify_email_to="a@example, b@example",
    )
    assert s.notification_channels == ["slack", "webhook", "email"]
    assert s.notify_email_recipients == ["a@example", "b@example"]
    assert s.smtp_configured


def test_payload_round_trips() -> None:
    p = NotificationPayload(
        title="t", body="b", severity="HIGH", alert_id=7, reason="new_alert", fields={"x": "y"}
    )
    assert NotificationPayload.from_dict(p.to_dict()) == p


@pytest.mark.asyncio
async def test_dispatch_with_no_channels_is_empty_and_hits_no_network() -> None:
    # No channels configured → returns {} without attempting any send.
    result = await dispatch(_settings(), NotificationPayload(title="t", body="b"))
    assert result == {}
