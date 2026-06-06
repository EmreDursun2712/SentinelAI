"""Shared enum classes used by ORM models and Pydantic schemas."""

from __future__ import annotations

import enum


class IngestionKind(str, enum.Enum):
    REPLAY = "REPLAY"
    STREAM = "STREAM"


class IngestionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Severity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(str, enum.Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    AUTO_RESPONDED = "AUTO_RESPONDED"
    AWAITING_ANALYST = "AWAITING_ANALYST"
    INVESTIGATED = "INVESTIGATED"
    REPORTED = "REPORTED"
    CLOSED = "CLOSED"


class AgentName(str, enum.Enum):
    DETECTION = "DETECTION"
    TRIAGE = "TRIAGE"
    RESPONSE = "RESPONSE"
    INVESTIGATION = "INVESTIGATION"
    REPORTING = "REPORTING"
    ANALYST = "ANALYST"  # human-driven actions logged through the same audit table


class AlertDisposition(str, enum.Enum):
    """Analyst verdict, orthogonal to the agent workflow status."""

    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    RESOLVED = "RESOLVED"


class ArtifactKind(str, enum.Enum):
    INVESTIGATION_PACKET = "INVESTIGATION_PACKET"
    FEATURE_IMPORTANCE = "FEATURE_IMPORTANCE"
    RELATED_ALERTS = "RELATED_ALERTS"
    RAW_FLOW = "RAW_FLOW"
    ATTACHMENT = "ATTACHMENT"


class ResponseActionType(str, enum.Enum):
    BLOCK_IP = "BLOCK_IP"
    RATE_LIMIT = "RATE_LIMIT"
    ISOLATE_HOST = "ISOLATE_HOST"
    NOTIFY_ANALYST = "NOTIFY_ANALYST"
    NO_ACTION = "NO_ACTION"
    # Phase 4 additions
    ESCALATE = "ESCALATE"            # raise to senior analyst, mark UNDER_REVIEW
    ISOLATE_ALERT = "ISOLATE_ALERT"  # segregate alert for special handling
    SUPPRESS_ALERT = "SUPPRESS_ALERT"  # mark FALSE_POSITIVE + close
    CREATE_TICKET = "CREATE_TICKET"  # simulated incident-ticket creation


class ResponseStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class IncidentKind(str, enum.Enum):
    PER_ALERT = "PER_ALERT"
    DAILY_SUMMARY = "DAILY_SUMMARY"
