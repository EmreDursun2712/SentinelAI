"""Unified audit trail — one "who did what, when" feed over scattered sources.

Audit-relevant events live in several tables (analyst ``agent_decisions``,
``model_activations``, human-touched ``response_actions``, and ``auth_sessions``
logins/logouts). This service normalizes each into a common :class:`AuditEntry`
shape and merges them into one reverse-chronological feed the SOC can read
without stitching tables together by hand.

Cross-source pagination is done in Python: each source is bounded by
``offset + limit`` (capped), the union is sorted by timestamp desc, then sliced.
That over-fetches slightly but keeps the query set simple and correct for the
volumes an audit viewer deals with.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDecision, AuthSession, ModelActivation, ResponseAction, User
from app.models.enums import AgentName

# Every audit category the feed can surface.
CATEGORIES = ("auth", "model", "analyst", "response")
_PER_SOURCE_CAP = 500


@dataclass
class AuditEntry:
    id: str  # synthetic, stable within a source (e.g. "auth:12:login")
    timestamp: datetime
    category: str
    actor: str | None
    action: str
    target: str | None
    detail: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "category": self.category,
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "detail": self.detail,
        }


def _fetch_cap(offset: int, limit: int) -> int:
    return min(offset + limit, _PER_SOURCE_CAP)


async def _auth_entries(
    session: AsyncSession, since: datetime | None, cap: int
) -> list[AuditEntry]:
    stmt = (
        select(AuthSession, User.username)
        .join(User, User.id == AuthSession.user_id)
        .order_by(desc(AuthSession.created_at))
        .limit(cap)
    )
    if since is not None:
        stmt = stmt.where(or_(AuthSession.created_at >= since, AuthSession.revoked_at >= since))
    entries: list[AuditEntry] = []
    for sess, username in (await session.execute(stmt)).all():
        entries.append(
            AuditEntry(
                id=f"auth:{sess.id}:login",
                timestamp=sess.created_at,
                category="auth",
                actor=username,
                action="login",
                target="session",
                detail=f"ip={sess.ip or '—'}",
            )
        )
        if sess.revoked_at is not None and (since is None or sess.revoked_at >= since):
            entries.append(
                AuditEntry(
                    id=f"auth:{sess.id}:logout",
                    timestamp=sess.revoked_at,
                    category="auth",
                    actor=username,
                    action="logout",
                    target="session",
                    detail="session revoked",
                )
            )
    return entries


async def _model_entries(
    session: AsyncSession, since: datetime | None, cap: int
) -> list[AuditEntry]:
    stmt = select(ModelActivation).order_by(desc(ModelActivation.created_at)).limit(cap)
    if since is not None:
        stmt = stmt.where(ModelActivation.created_at >= since)
    entries: list[AuditEntry] = []
    for a in (await session.execute(stmt)).scalars().all():
        entries.append(
            AuditEntry(
                id=f"model:{a.id}",
                timestamp=a.created_at,
                category="model",
                actor=a.actor,
                action=a.action,  # activate | rollback
                target=f"model version #{a.model_version_id}",
                detail=a.reason,
            )
        )
    return entries


async def _analyst_entries(
    session: AsyncSession, since: datetime | None, cap: int
) -> list[AuditEntry]:
    stmt = (
        select(AgentDecision)
        .where(AgentDecision.agent == AgentName.ANALYST)
        .order_by(desc(AgentDecision.created_at))
        .limit(cap)
    )
    if since is not None:
        stmt = stmt.where(AgentDecision.created_at >= since)
    entries: list[AuditEntry] = []
    for d in (await session.execute(stmt)).scalars().all():
        decision = d.decision or {}
        reasoning = d.reasoning or {}
        if "disposition_to" in decision:
            action = f"disposition → {decision['disposition_to']}"
        else:
            verb = str(decision.get("verb", "action"))
            action = f"{verb} {decision.get('action_type') or ''}".strip()
        entries.append(
            AuditEntry(
                id=f"analyst:{d.id}",
                timestamp=d.created_at,
                category="analyst",
                actor=reasoning.get("analyst_id") or "analyst",
                action=action,
                target=f"alert #{d.alert_id}",
                detail=reasoning.get("note") or reasoning.get("reason"),
            )
        )
    return entries


async def _response_entries(
    session: AsyncSession, since: datetime | None, cap: int
) -> list[AuditEntry]:
    # Only human-touched actions (approved or rejected) belong in the audit feed;
    # auto-executed simulations are workflow noise, not accountability events.
    stmt = (
        select(ResponseAction)
        .where(
            or_(
                ResponseAction.approved_by.isnot(None),
                ResponseAction.rejection_reason.isnot(None),
            )
        )
        .order_by(desc(ResponseAction.updated_at))
        .limit(cap)
    )
    if since is not None:
        stmt = stmt.where(ResponseAction.updated_at >= since)
    entries: list[AuditEntry] = []
    for a in (await session.execute(stmt)).scalars().all():
        rejected = a.rejection_reason is not None
        entries.append(
            AuditEntry(
                id=f"response:{a.id}",
                timestamp=a.updated_at,
                category="response",
                actor=a.approved_by or "analyst",
                action=f"{'rejected' if rejected else 'approved'} {a.action_type.value}",
                target=f"alert #{a.alert_id}",
                detail=a.rejection_reason,
            )
        )
    return entries


_SOURCES = {
    "auth": _auth_entries,
    "model": _model_entries,
    "analyst": _analyst_entries,
    "response": _response_entries,
}


async def list_audit(
    session: AsyncSession,
    *,
    categories: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
    since: datetime | None = None,
) -> tuple[list[AuditEntry], bool]:
    """Return ``(page, has_more)`` of merged, newest-first audit entries."""
    wanted = [c for c in (categories or CATEGORIES) if c in _SOURCES]
    cap = _fetch_cap(offset, limit)

    merged: list[AuditEntry] = []
    for cat in wanted:
        merged.extend(await _SOURCES[cat](session, since, cap))

    merged.sort(key=lambda e: e.timestamp, reverse=True)
    page = merged[offset : offset + limit]
    has_more = len(merged) > offset + limit
    return page, has_more
