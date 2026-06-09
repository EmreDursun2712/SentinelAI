"""SQLAlchemy ORM models.

Importing this package registers every model class with `Base.metadata`, which
Alembic's autogenerate machinery and our test suite rely on. New models must be
added here to be discoverable.
"""

from app.models.agent_decision import AgentDecision
from app.models.alert import Alert
from app.models.alert_artifact import AlertArtifact
from app.models.auth_session import AuthSession
from app.models.enums import (
    AgentName,
    AlertDisposition,
    AlertStatus,
    ArtifactKind,
    DriftStatus,
    ExecutionMode,
    IncidentKind,
    IngestionKind,
    IngestionStatus,
    ResponseActionType,
    ResponseStatus,
    Role,
    RollbackStatus,
    Severity,
    TaskKind,
    TaskStatus,
)
from app.models.incident_report import IncidentReport
from app.models.ingestion_job import IngestionJob
from app.models.mixins import CreatedAtMixin, TimestampMixin
from app.models.model_activation import ModelActivation
from app.models.model_drift import ModelDriftSnapshot
from app.models.model_shadow_eval import ModelShadowEval
from app.models.model_version import ModelVersion
from app.models.network_event import NetworkEvent
from app.models.response_action import ResponseAction
from app.models.task import Task
from app.models.user import User

__all__ = [
    "AgentDecision",
    "AgentName",
    "Alert",
    "AlertArtifact",
    "AlertDisposition",
    "AlertStatus",
    "ArtifactKind",
    "AuthSession",
    "CreatedAtMixin",
    "DriftStatus",
    "ExecutionMode",
    "IncidentKind",
    "IncidentReport",
    "IngestionJob",
    "IngestionKind",
    "IngestionStatus",
    "ModelActivation",
    "ModelDriftSnapshot",
    "ModelShadowEval",
    "ModelVersion",
    "NetworkEvent",
    "ResponseAction",
    "ResponseActionType",
    "ResponseStatus",
    "Role",
    "RollbackStatus",
    "Severity",
    "Task",
    "TaskKind",
    "TaskStatus",
    "TimestampMixin",
    "User",
]
