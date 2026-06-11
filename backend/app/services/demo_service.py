"""Demo helper: wipe operational data so the dashboard returns to zero.

Guarded by ``settings.demo_reset_enabled`` at the API layer. Clears the
event / alert / response / report / drift tables (children first) while
preserving users, auth sessions, and the trained model registry. Postgres uses
``TRUNCATE ... RESTART IDENTITY CASCADE`` so IDs restart at 1 for a clean live
demo; other dialects fall back to ordered ``DELETE``s.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    AgentDecision,
    Alert,
    AlertArtifact,
    IncidentReport,
    IngestionJob,
    ModelActivation,
    ModelDriftSnapshot,
    ModelShadowEval,
    NetworkEvent,
    ResponseAction,
    Task,
)

# Child tables first so the ordered-DELETE fallback respects foreign keys; the
# list also doubles as the manifest of "what a reset wipes". Deliberately
# excludes users, auth_sessions, model_versions, and alembic_version.
_WIPE_ORDER = (
    ResponseAction,
    AgentDecision,
    AlertArtifact,
    IncidentReport,
    Alert,
    NetworkEvent,
    IngestionJob,
    ModelDriftSnapshot,
    ModelActivation,
    ModelShadowEval,
    Task,
)


async def reset_demo_data(session: AsyncSession) -> dict[str, int]:
    """Delete every operational row; return the per-table count removed."""
    counts: dict[str, int] = {}
    for model in _WIPE_ORDER:
        n = (await session.execute(select(func.count()).select_from(model))).scalar_one()
        counts[model.__tablename__] = int(n or 0)

    if "postgresql" in get_settings().database_url:
        tables = ", ".join(model.__tablename__ for model in _WIPE_ORDER)
        await session.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    else:
        for model in _WIPE_ORDER:  # already ordered children → parents
            await session.execute(delete(model))

    await session.commit()
    return counts
