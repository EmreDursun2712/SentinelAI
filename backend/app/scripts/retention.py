"""Retention CLI: report (dry-run) or apply the data-retention policy.

    python -m app.scripts.retention            # dry-run (default; no writes)
    python -m app.scripts.retention --apply    # actually delete/archive

Prints a JSON summary. Configure via SENTINEL_RETENTION_{EVENTS,ALERTS,REPORTS}_DAYS
(0 = disabled). See docs/DATA_RETENTION.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.config import get_settings
from app.core.db import dispose_engine, init_engine, session_scope
from app.services.retention_service import apply_retention


async def _run(dry_run: bool) -> dict:
    settings = get_settings()
    init_engine(settings.database_url)
    try:
        async with session_scope() as session:
            return await apply_retention(session, settings=settings, dry_run=dry_run)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SentinelAI data retention")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually delete/archive (default is a dry-run that only reports).",
    )
    args = parser.parse_args(argv)
    summary = asyncio.run(_run(dry_run=not args.apply))
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
