#!/usr/bin/env bash
# Backend container entrypoint.
#
# 1. Apply Alembic migrations to head (idempotent — fast no-op on re-run).
# 2. `exec` uvicorn so it becomes PID 1 inside the container, which means
#    SIGTERM from `docker stop` reaches it directly and lifespan shutdown
#    runs cleanly.
#
# Any args passed by `docker compose run/up` are forwarded to uvicorn — that's
# how compose's `command: ["--reload"]` flows through.

set -euo pipefail

echo "[entrypoint] applying database migrations..."
alembic upgrade head

echo "[entrypoint] starting uvicorn on 0.0.0.0:8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 "$@"
