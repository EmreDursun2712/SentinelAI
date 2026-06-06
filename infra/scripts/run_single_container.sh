#!/usr/bin/env bash
# Build and run SentinelAI as one Docker container named "sentinelai".

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
cd "${REPO_ROOT}"

IMAGE_NAME="${SENTINELAI_IMAGE_NAME:-sentinelai:single}"
CONTAINER_NAME="${SENTINELAI_CONTAINER_NAME:-sentinelai}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
    FRONTEND_PORT="${FRONTEND_PORT:-5173}"
    BACKEND_PORT="${BACKEND_PORT:-8000}"
else
    cp .env.example .env
fi

command -v docker >/dev/null 2>&1 || {
    echo "docker is required" >&2
    exit 1
}

docker build -t "${IMAGE_NAME}" .

existing="$(docker ps -aq --filter "name=^/${CONTAINER_NAME}$")"
if [[ -n "${existing}" ]]; then
    docker rm -f "${CONTAINER_NAME}" >/dev/null
fi

docker run -d \
    --name "${CONTAINER_NAME}" \
    --env-file .env \
    -p "${FRONTEND_PORT}:5173" \
    -p "${BACKEND_PORT}:8000" \
    -v sentinelai_pgdata:/var/lib/postgresql/data \
    "${IMAGE_NAME}" >/dev/null

echo "SentinelAI container started."
echo "Dashboard: http://localhost:${FRONTEND_PORT}"
echo "Backend:   http://localhost:${BACKEND_PORT}"
