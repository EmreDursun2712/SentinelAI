#!/usr/bin/env bash
# One-shot setup: from a fresh clone to a working demo.
#
#   1. Ensure .env exists (copy from .env.example if not).
#   2. docker compose up -d --build  (postgres + backend + frontend).
#   3. Wait for backend /health to respond.
#   4. If no model is staged at ml/artifacts/latest/, run seed.sh.
#   5. Restart backend so it loads the model.
#   6. Wait for /detection/model to report loaded=true.
#   7. Print URLs and the next-step pointer (smoke test).
#
# Safe to re-run — every step is idempotent. Honors SENTINELAI_BASE_URL.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
cd "${REPO_ROOT}"

BASE="${SENTINELAI_BASE_URL:-http://localhost:8000}"
UI_BASE="${SENTINELAI_UI_URL:-http://localhost:5173}"

# ---------- output helpers ----------

if [[ -t 1 ]]; then
    C_STEP=$'\033[36m'; C_OK=$'\033[32m'; C_FAIL=$'\033[31m'
    C_DIM=$'\033[90m'; C_RESET=$'\033[0m'
else
    C_STEP=""; C_OK=""; C_FAIL=""; C_DIM=""; C_RESET=""
fi
step() { printf "\n%s==>%s %s\n" "$C_STEP" "$C_RESET" "$1"; }
ok()   { printf "    %s✓%s %s\n"  "$C_OK"   "$C_RESET" "$1"; }
note() { printf "    %s· %s%s\n"  "$C_DIM"  "$1" "$C_RESET"; }
fail() { printf "    %s✗%s %s\n"  "$C_FAIL" "$C_RESET" "$1" >&2; exit 1; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

# ---------- preflight ----------

require_cmd docker
require_cmd curl
docker compose version >/dev/null 2>&1 \
    || fail "docker compose v2 not available (try upgrading Docker Desktop)"

# ---------- 1. .env ----------

step "1. Environment file"
if [[ -f .env ]]; then
    ok ".env already present"
else
    cp .env.example .env
    ok "copied .env.example → .env"
fi

# ---------- 2. bring up the stack ----------

step "2. docker compose up -d --build"
docker compose up -d --build
ok "containers started"

# ---------- 3. wait for backend /health ----------

step "3. Wait for backend /health"
attempts=0
until curl -fsS "${BASE}/health" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [[ "${attempts}" -gt 60 ]]; then
        docker compose logs --tail=50 backend >&2 || true
        fail "backend did not become healthy in 120s — see logs above"
    fi
    sleep 2
done
ok "backend healthy at ${BASE}/health"

# ---------- 4. seed model if absent ----------

step "4. Detection model"
LATEST_DIR="${REPO_ROOT}/ml/artifacts/latest"
NEEDS_SEED=0
if [[ ! -d "${LATEST_DIR}" ]] || [[ -z "$(ls -A "${LATEST_DIR}" 2>/dev/null)" ]]; then
    NEEDS_SEED=1
fi

if [[ "${NEEDS_SEED}" -eq 1 ]]; then
    note "no model staged — running seed.sh"
    SENTINELAI_SKIP_RESTART=1 bash "${SCRIPT_DIR}/seed.sh"
    ok "model trained"
    step "5. Restart backend to load the new model"
    docker compose restart backend >/dev/null
    ok "backend restarted"
else
    ok "model already staged at ml/artifacts/latest/"
fi

# ---------- 6. wait for model to be loaded ----------

step "6. Wait for detection model to register"
attempts=0
until curl -fsS "${BASE}/api/v1/detection/model" 2>/dev/null \
        | grep -q '"loaded": true\|"loaded":true'; do
    attempts=$((attempts + 1))
    if [[ "${attempts}" -gt 30 ]]; then
        fail "model never reported loaded — check: curl ${BASE}/api/v1/detection/model"
    fi
    sleep 2
done
ok "model registered with the backend"

# ---------- done ----------

printf "\n%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n" \
    "$C_OK" "$C_RESET"
printf "%sSentinelAI is ready.%s\n" "$C_OK" "$C_RESET"
printf "  · Dashboard:  %s\n" "${UI_BASE}"
printf "  · Backend:    %s\n" "${BASE}"
printf "  · API docs:   %s/docs\n" "${BASE}"
printf "\nNext: run the end-to-end smoke test to populate alerts and reports:\n"
printf "  %sbash infra/scripts/smoke_demo.sh%s    # or: make smoke\n" \
    "$C_DIM" "$C_RESET"
