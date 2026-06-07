#!/usr/bin/env bash
# End-to-end gate: bring up the stack, train + stage a model, run the smoke test
# in the default (simulated) mode, then tear everything down — including the DB
# volume. Safe to run in CI or locally (needs ports 8000/5432/6379 free).
#
# Honors SENTINELAI_BASE_URL (default http://localhost:8000).

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
cd "${REPO_ROOT}"

BASE="${SENTINELAI_BASE_URL:-http://localhost:8000}"
export BACKEND_BOOTSTRAP_ADMIN_USERNAME="${BACKEND_BOOTSTRAP_ADMIN_USERNAME:-admin}"
export BACKEND_BOOTSTRAP_ADMIN_PASSWORD="${BACKEND_BOOTSTRAP_ADMIN_PASSWORD:-e2e-admin-pw}"

step() { printf "\n==> %s\n" "$1"; }

cleanup() {
    step "Tearing down (down -v)"
    docker compose down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

step "Bring up postgres + redis + backend"
docker compose up -d --build postgres redis backend

step "Train + stage a model (sklearn-aligned, inside the backend image)"
docker compose run --rm --no-deps \
    -v "${REPO_ROOT}/ml:/work/ml" -w /work -e PYTHONPATH=/work \
    --entrypoint python backend \
    -m ml.train --synthetic 8000 --n-estimators 40 --log-level WARNING

step "Restart backend so it loads the freshly staged model"
docker compose restart backend

step "Wait for backend health"
for _ in $(seq 1 60); do
    curl -fsS "${BASE}/health" >/dev/null 2>&1 && break
    sleep 2
done

step "Wait for the detection model to register"
TOKEN=""
for _ in $(seq 1 30); do
    TOKEN=$(curl -fsS -X POST -H 'Content-Type: application/json' \
        -d "{\"username\":\"${BACKEND_BOOTSTRAP_ADMIN_USERNAME}\",\"password\":\"${BACKEND_BOOTSTRAP_ADMIN_PASSWORD}\"}" \
        "${BASE}/api/v1/auth/login" 2>/dev/null | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4 || true)
    if [[ -n "${TOKEN}" ]] && curl -fsS -H "Authorization: Bearer ${TOKEN}" \
        "${BASE}/api/v1/detection/model" 2>/dev/null | grep -q '"loaded": *true'; then
        break
    fi
    sleep 2
done
[[ -n "${TOKEN}" ]] || { echo "could not authenticate / load model"; exit 1; }

step "Run the smoke test (default simulated mode)"
SENTINELAI_BASE_URL="${BASE}" \
SENTINELAI_USERNAME="${BACKEND_BOOTSTRAP_ADMIN_USERNAME}" \
SENTINELAI_PASSWORD="${BACKEND_BOOTSTRAP_ADMIN_PASSWORD}" \
    bash "${SCRIPT_DIR}/smoke_demo.sh"

step "E2E passed"
