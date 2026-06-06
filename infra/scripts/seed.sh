#!/usr/bin/env bash
# Train a detection model and refresh the backend so it picks it up.
#
# Idempotent:
#   * Reuses ml/.venv if it already exists.
#   * Skips the heavy pip install if scikit-learn is already importable in
#     that venv.
#   * Overwrites ml/artifacts/latest/ in place — re-running just produces
#     a fresh model.
#
# By default trains on 50k synthetic CIC-IDS2017-like rows (fast: ~20 s on
# an M-series laptop). Override with environment variables:
#
#   SENTINELAI_TRAIN_ROWS=200000 bash infra/scripts/seed.sh
#   SENTINELAI_TRAIN_ARGS="--data ml/data/cic-ids-2017/" bash infra/scripts/seed.sh
#
# Skips the backend restart when there is no running stack — `bootstrap.sh`
# handles the ordering. Pass SENTINELAI_SKIP_RESTART=1 to force-skip.

set -euo pipefail

# Locate repo root from this script's location so `bash infra/scripts/seed.sh`
# and `./infra/scripts/seed.sh` both work regardless of cwd.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
cd "${REPO_ROOT}"

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

# ---------- 1. python venv for the ml package ----------

VENV="${REPO_ROOT}/ml/.venv"
PY="${VENV}/bin/python"

step "1. Python venv for the ml package"
if [[ ! -x "${PY}" ]]; then
    note "creating venv at ${VENV}"
    command -v python3 >/dev/null 2>&1 \
        || fail "python3 not on PATH — install Python 3.12 first"
    python3 -m venv "${VENV}"
    ok "venv created"
else
    ok "venv already exists at ${VENV}"
fi

# ---------- 2. install ml deps (skip if already present) ----------

step "2. Install ml dependencies"
if "${PY}" -c "import sklearn, joblib, pandas, numpy" 2>/dev/null; then
    ok "dependencies already installed"
else
    note "running pip install -e ml/ (this is slow on first run)"
    "${PY}" -m pip install --quiet --upgrade pip
    "${PY}" -m pip install --quiet -e "${REPO_ROOT}/ml"
    ok "dependencies installed"
fi

# ---------- 3. train ----------

ROWS="${SENTINELAI_TRAIN_ROWS:-50000}"
EXTRA_ARGS="${SENTINELAI_TRAIN_ARGS:-}"

step "3. Train detection model"
if [[ -n "${EXTRA_ARGS}" ]]; then
    note "passthrough args: ${EXTRA_ARGS}"
    # shellcheck disable=SC2086  # we want word splitting on EXTRA_ARGS
    "${PY}" -m ml.train ${EXTRA_ARGS}
else
    note "synthetic rows: ${ROWS}"
    "${PY}" -m ml.train --synthetic "${ROWS}"
fi
ok "training complete — artifacts under ml/artifacts/latest/"

# ---------- 4. restart backend so it loads the new model ----------

step "4. Refresh backend"
if [[ "${SENTINELAI_SKIP_RESTART:-0}" == "1" ]]; then
    note "SENTINELAI_SKIP_RESTART=1 — leaving backend untouched"
elif ! command -v docker >/dev/null 2>&1; then
    note "docker not on PATH — start the backend manually to pick up the new model"
elif ! docker compose ps --status running backend 2>/dev/null | grep -q backend; then
    note "backend container not running — 'docker compose up -d backend' to start it"
else
    docker compose restart backend >/dev/null
    ok "backend restarted"
fi

printf "\n%sSeed complete.%s Model is staged at ml/artifacts/latest/.\n" \
    "$C_OK" "$C_RESET"
