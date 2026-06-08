"""Helpers for list-endpoint total counts.

List endpoints keep their array (or existing envelope) body for backwards
compatibility and expose the unpaginated total via the ``X-Total-Count`` header
(which CORS exposes to the browser). The frontend reads it for real pagination.
"""

from __future__ import annotations

from fastapi import Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

TOTAL_COUNT_HEADER = "X-Total-Count"


async def count_for(session: AsyncSession, stmt: Select) -> int:
    """Total rows for a filtered, *unpaginated* SELECT (no order/limit/offset)."""
    result = await session.execute(select(func.count()).select_from(stmt.subquery()))
    return int(result.scalar_one() or 0)


def set_total_count(response: Response, total: int) -> None:
    response.headers[TOTAL_COUNT_HEADER] = str(int(total))
