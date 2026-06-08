"""Dump the OpenAPI schema to stdout (deterministic) for frontend codegen.

    python -m app.scripts.dump_openapi > openapi.json

The committed ``backend/openapi.json`` feeds ``npm run generate:api-types`` in
the frontend (openapi-typescript). CI regenerates both and diffs to catch drift.
"""

from __future__ import annotations

import json
import sys

from app.main import create_app


def main() -> int:
    schema = create_app().openapi()
    # sort_keys for a stable, diff-friendly file.
    json.dump(schema, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
