"""External alert notifications — Slack, generic webhook, and SMTP email.

Off by default (``settings.notifications_enabled``). When enabled, a qualifying
alert (severity ≥ ``notify_min_severity``, or any analyst-``CONFIRMED`` alert)
fans out to every *configured* channel. Delivery runs on the task queue
(``notify_task``) so an outbound Slack/SMTP call never blocks the request; if no
worker/Redis is present the enqueue helper falls back to a best-effort in-process
dispatch so a single-node demo still notifies.

Every send is best-effort and isolated: one channel failing (or being
misconfigured) never raises into the caller or blocks the others.
"""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.queue import get_task_queue

logger = get_logger(__name__)

# Severity rank for threshold comparison (higher = more severe).
_SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

NOTIFY_TASK = "notify_task"


@dataclass
class NotificationPayload:
    title: str
    body: str
    severity: str | None = None
    alert_id: int | None = None
    reason: str = "alert"  # "new_alert" | "confirmed" | ...
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "severity": self.severity,
            "alert_id": self.alert_id,
            "reason": self.reason,
            "fields": self.fields,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NotificationPayload:
        return cls(
            title=str(data.get("title", "SentinelAI alert")),
            body=str(data.get("body", "")),
            severity=data.get("severity"),
            alert_id=data.get("alert_id"),
            reason=str(data.get("reason", "alert")),
            fields=dict(data.get("fields") or {}),
        )


def severity_meets_threshold(severity: str | None, minimum: str) -> bool:
    """True when ``severity`` is at least ``minimum`` on the LOW→CRITICAL scale."""
    if severity is None:
        return False
    return _SEVERITY_RANK.get(severity.upper(), 0) >= _SEVERITY_RANK.get(minimum.upper(), 99)


def should_notify(settings: Settings, severity: str | None, *, reason: str) -> bool:
    """Gate: enabled, a channel configured, and severity/reason qualifies."""
    if not settings.notifications_enabled or not settings.notification_channels:
        return False
    if reason == "confirmed":
        return True  # an analyst-confirmed alert always warrants a heads-up
    return severity_meets_threshold(severity, settings.notify_min_severity)


# ---------------------------------------------------------------------------
# Channel senders — each returns "ok" / "skipped" / "error:<msg>"; never raises.
# ---------------------------------------------------------------------------


async def _send_slack(settings: Settings, payload: NotificationPayload) -> str:
    url = settings.slack_webhook_url
    if not url:
        return "skipped"
    sev = f"[{payload.severity}] " if payload.severity else ""
    lines = [f"*{sev}{payload.title}*", payload.body]
    lines += [f"• {k}: {v}" for k, v in payload.fields.items()]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"text": "\n".join(lines)})
            resp.raise_for_status()
        return "ok"
    except Exception as exc:  # network / non-2xx
        logger.warning("notify.slack_failed", error=str(exc))
        return f"error:{exc}"


async def _send_webhook(settings: Settings, payload: NotificationPayload) -> str:
    url = settings.notify_webhook_url
    if not url:
        return "skipped"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"source": "sentinelai", **payload.to_dict()})
            resp.raise_for_status()
        return "ok"
    except Exception as exc:
        logger.warning("notify.webhook_failed", error=str(exc))
        return f"error:{exc}"


def _send_email_sync(settings: Settings, payload: NotificationPayload) -> str:
    if not settings.smtp_configured:
        return "skipped"
    msg = EmailMessage()
    sev = f"[{payload.severity}] " if payload.severity else ""
    msg["Subject"] = f"SentinelAI {sev}{payload.title}"
    msg["From"] = settings.smtp_from or "sentinelai@localhost"
    msg["To"] = ", ".join(settings.notify_email_recipients)
    body_lines = [payload.body, ""]
    body_lines += [f"{k}: {v}" for k, v in payload.fields.items()]
    msg.set_content("\n".join(body_lines))
    try:
        with smtplib.SMTP(
            settings.smtp_host or "localhost", settings.smtp_port, timeout=15
        ) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
        return "ok"
    except Exception as exc:
        logger.warning("notify.email_failed", error=str(exc))
        return f"error:{exc}"


async def dispatch(settings: Settings, payload: NotificationPayload) -> dict[str, str]:
    """Send ``payload`` to every configured channel; return per-channel status."""
    results: dict[str, str] = {}
    if "slack" in settings.notification_channels:
        results["slack"] = await _send_slack(settings, payload)
    if "webhook" in settings.notification_channels:
        results["webhook"] = await _send_webhook(settings, payload)
    if "email" in settings.notification_channels:
        results["email"] = await asyncio.to_thread(_send_email_sync, settings, payload)
    logger.info(
        "notify.dispatched",
        reason=payload.reason,
        alert_id=payload.alert_id,
        severity=payload.severity,
        results=results,
    )
    return results


# ---------------------------------------------------------------------------
# Enqueue — prefer the task queue; fall back to in-process best-effort.
# ---------------------------------------------------------------------------


async def enqueue_notification(payload: NotificationPayload) -> None:
    """Queue a notification; if there's no worker, dispatch inline (best-effort)."""
    queue = get_task_queue()
    job_id: str | None = None
    try:
        job_id = await queue.enqueue(NOTIFY_TASK, payload.to_dict())
    except Exception as exc:  # pragma: no cover - queue misbehaving
        logger.warning("notify.enqueue_failed", error=str(exc))
    if job_id is None:
        # No worker/Redis (dev/demo): send now without blocking the caller.
        asyncio.create_task(dispatch(get_settings(), payload))  # noqa: RUF006


async def notify_alert(
    *,
    alert_id: int,
    prediction: str | None,
    severity: str | None,
    src_ip: str | None,
    dst_ip: str | None,
    confidence: float | None = None,
    reason: str = "new_alert",
) -> None:
    """Build + enqueue a notification for an alert if it qualifies (else no-op)."""
    settings = get_settings()
    if not should_notify(settings, severity, reason=reason):
        return
    verb = "confirmed by analyst" if reason == "confirmed" else "raised"
    payload = NotificationPayload(
        title=f"{severity or 'ALERT'} {prediction or 'event'} alert #{alert_id} {verb}",
        body=f"Alert #{alert_id} ({prediction or 'unknown'}) from {src_ip} → {dst_ip}.",
        severity=severity,
        alert_id=alert_id,
        reason=reason,
        fields={
            "source": src_ip or "—",
            "destination": dst_ip or "—",
            "prediction": prediction or "—",
            **({"confidence": f"{confidence:.2f}"} if confidence is not None else {}),
        },
    )
    await enqueue_notification(payload)
