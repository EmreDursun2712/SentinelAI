"""Response rule engine.

Pure-Python: given an ``Alert`` (already triaged with severity + priority),
return an ordered list of ``Recommendation`` objects. Each carries an
``action_type``, an ``auto_execute`` flag, a human-readable ``rationale``,
and a JSON payload describing what *would* be sent to a real downstream
system if this were not simulated.

Policy summary:

    CRITICAL    auto-block source + create incident ticket + notify
                (+ isolate target if BruteForce / Infiltration)
    HIGH        auto-block source + create ticket + notify
                (+ rate-limit if DDoS family)
    MEDIUM      recommend block (analyst approval) + escalate + notify
    LOW         notify; if confidence < 0.6, also recommend suppress
    BENIGN      recommend suppress + notify

Side effects only fire when an action is executed (auto or via /approve):

    SUPPRESS_ALERT → alert.disposition = FALSE_POSITIVE, status = CLOSED
    ESCALATE       → alert.disposition = UNDER_REVIEW
    everything else is informational / logged-payload only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from app.models import Alert
from app.models.enums import AlertDisposition, AlertStatus, ResponseActionType, Severity

LOW_CONFIDENCE_SUPPRESS_THRESHOLD: Final[float] = 0.60


@dataclass(frozen=True)
class Recommendation:
    """Single proposed response action."""

    action_type: ResponseActionType
    auto_execute: bool
    rationale: str
    payload: dict[str, Any] = field(default_factory=dict)


# ---------- per-action builders -------------------------------------------


def _notify(message: str) -> Recommendation:
    return Recommendation(
        action_type=ResponseActionType.NOTIFY_ANALYST,
        auto_execute=True,  # writing to the dashboard is harmless
        rationale=message,
        payload={"channel": "dashboard", "message": message},
    )


def _ticket(alert: Alert, kind: str) -> Recommendation:
    sev = alert.severity.value if alert.severity is not None else "UNKNOWN"
    title = f"{sev} {alert.prediction} from {alert.src_ip}"
    return Recommendation(
        action_type=ResponseActionType.CREATE_TICKET,
        auto_execute=True,  # creating a placeholder ticket is informational
        rationale=f"Create {kind} ticket for alert #{alert.id}.",
        payload={
            "ticket_id": f"SENTINEL-{alert.id}",
            "title": title,
            "kind": kind,
            "severity": sev,
        },
    )


def _block(alert: Alert, *, auto: bool, duration: str, reason: str) -> Recommendation:
    return Recommendation(
        action_type=ResponseActionType.BLOCK_IP,
        auto_execute=auto,
        rationale=reason,
        payload={"target_ip": alert.src_ip, "duration": duration, "scope": "perimeter"},
    )


def _rate_limit(alert: Alert, *, auto: bool, rate: str) -> Recommendation:
    return Recommendation(
        action_type=ResponseActionType.RATE_LIMIT,
        auto_execute=auto,
        rationale=(
            f"DDoS pattern from {alert.src_ip} on dst_port={alert.dst_port}; throttle to {rate}."
        ),
        payload={"target_ip": alert.src_ip, "rate": rate, "scope": "perimeter"},
    )


def _isolate_host(alert: Alert, *, auto: bool, reason: str) -> Recommendation:
    return Recommendation(
        action_type=ResponseActionType.ISOLATE_HOST,
        auto_execute=auto,
        rationale=reason,
        payload={"target_ip": alert.dst_ip, "scope": "edr_quarantine"},
    )


def _escalate(alert: Alert) -> Recommendation:
    return Recommendation(
        action_type=ResponseActionType.ESCALATE,
        auto_execute=False,  # human-in-the-loop by definition
        rationale="Escalate to senior analyst for review.",
        payload={"target_disposition": AlertDisposition.UNDER_REVIEW.value},
    )


def _suppress(alert: Alert, *, reason: str) -> Recommendation:
    return Recommendation(
        action_type=ResponseActionType.SUPPRESS_ALERT,
        auto_execute=False,  # disposition change requires analyst sign-off
        rationale=reason,
        payload={
            "target_disposition": AlertDisposition.FALSE_POSITIVE.value,
            "reason": "low_confidence_or_benign",
        },
    )


def _no_action(alert: Alert, reason: str) -> Recommendation:
    return Recommendation(
        action_type=ResponseActionType.NO_ACTION,
        auto_execute=True,
        rationale=reason,
        payload={},
    )


# ---------- main entry point ----------------------------------------------


def recommend_actions(alert: Alert) -> list[Recommendation]:
    """Produce the recommendation list for ``alert``.

    The list always contains at least one item (often a NOTIFY_ANALYST) so the
    dashboard surfaces the alert in the analyst queue.
    """
    # Closed alerts get nothing — already terminal.
    if alert.status == AlertStatus.CLOSED:
        return []

    # If the analyst already marked it FALSE_POSITIVE, don't re-suggest suppression.
    if alert.disposition == AlertDisposition.FALSE_POSITIVE:
        return [_notify("Alert is already marked FALSE_POSITIVE; informational only.")]

    severity = alert.severity
    family = (alert.prediction or "").strip()
    confidence = alert.confidence or 0.0
    is_brute_or_intrusion = any(k in family for k in ("BruteForce", "Infiltration"))
    is_ddos = "DDoS" in family
    is_benign = family.upper() == "BENIGN"

    # BENIGN-classified alerts are usually a model hiccup — suggest suppress.
    if is_benign:
        return [
            _suppress(alert, reason=f"Predicted BENIGN at confidence {confidence:.2f}; suppress."),
            _notify(f"Possible false positive (BENIGN from {alert.src_ip})."),
        ]

    if severity == Severity.CRITICAL:
        recs = [
            _block(
                alert,
                auto=True,
                duration="24h",
                reason=f"CRITICAL {family} from {alert.src_ip} — auto-block.",
            )
        ]
        if is_brute_or_intrusion:
            recs.append(
                _isolate_host(
                    alert,
                    auto=True,
                    reason=(
                        f"{family} on {alert.dst_ip}:{alert.dst_port} — "
                        "isolate target host to limit lateral movement."
                    ),
                )
            )
        if is_ddos:
            recs.append(_rate_limit(alert, auto=True, rate="10/sec"))
        recs.append(_ticket(alert, kind="incident"))
        recs.append(_notify(f"CRITICAL {family} — auto-responded; please review for follow-up."))
        return recs

    if severity == Severity.HIGH:
        recs = [
            _block(
                alert,
                auto=True,
                duration="6h",
                reason=f"HIGH severity {family} — auto-block source IP.",
            )
        ]
        if is_ddos:
            recs.append(_rate_limit(alert, auto=True, rate="30/sec"))
        recs.append(_ticket(alert, kind="high"))
        recs.append(_notify(f"HIGH {family} — auto-actions taken."))
        return recs

    if severity == Severity.MEDIUM:
        return [
            _block(
                alert,
                auto=False,
                duration="1h",
                reason=f"MEDIUM {family} — recommend block; awaiting analyst approval.",
            ),
            _escalate(alert),
            _notify(f"MEDIUM {family} from {alert.src_ip} — awaiting decision."),
        ]

    # LOW or no severity yet.
    recs: list[Recommendation] = []
    if confidence < LOW_CONFIDENCE_SUPPRESS_THRESHOLD:
        recs.append(
            _suppress(
                alert,
                reason=(
                    f"LOW severity and confidence={confidence:.2f} < "
                    f"{LOW_CONFIDENCE_SUPPRESS_THRESHOLD:.2f} — likely false positive."
                ),
            )
        )
    recs.append(_notify(f"LOW {family or 'event'} from {alert.src_ip} — informational."))
    return recs
