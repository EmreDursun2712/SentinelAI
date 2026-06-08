#!/usr/bin/env bash
# End-to-end smoke test for SentinelAI.
#
# Exercises the full pipeline against a running backend:
#   health → model loaded → ingest sample CSV → run detection
#   → list alerts → investigate one → set disposition → generate report
#   → approve pending response action → daily summary
#
# Requirements:
#   * The backend is running and reachable at $SENTINELAI_BASE_URL
#     (default: http://localhost:8000)
#   * A trained model has been staged at ml/artifacts/latest/
#     (run `python -m ml.train --synthetic 50000` first)
#   * curl + jq installed
#
# Exit codes:
#   0   every step passed
#   1   a step failed (look at the last "✗" line for the reason)

set -euo pipefail

BASE="${SENTINELAI_BASE_URL:-http://localhost:8000}"
API="$BASE/api/v1"

# Credentials for the protected API. Default to the bootstrap admin; override
# with SENTINELAI_USERNAME / SENTINELAI_PASSWORD. The password has no default —
# set it (or BACKEND_BOOTSTRAP_ADMIN_PASSWORD) so the smoke test can log in.
SMOKE_USER="${SENTINELAI_USERNAME:-admin}"
SMOKE_PASS="${SENTINELAI_PASSWORD:-${BACKEND_BOOTSTRAP_ADMIN_PASSWORD:-}}"

# ---------- output helpers ----------

if [[ -t 1 ]]; then
    C_STEP=$'\033[36m'
    C_OK=$'\033[32m'
    C_FAIL=$'\033[31m'
    C_DIM=$'\033[90m'
    C_RESET=$'\033[0m'
else
    C_STEP=""; C_OK=""; C_FAIL=""; C_DIM=""; C_RESET=""
fi

step() { printf "\n%s==>%s %s\n" "$C_STEP" "$C_RESET" "$1"; }
ok()   { printf "    %s✓%s %s\n"  "$C_OK"   "$C_RESET" "$1"; }
note() { printf "    %s· %s%s\n"  "$C_DIM"  "$1" "$C_RESET"; }
fail() {
    printf "    %s✗%s %s\n" "$C_FAIL" "$C_RESET" "$1" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

# ---------- preflight ----------

require_cmd curl
require_cmd jq

printf "%sSentinelAI smoke test%s — target: %s\n" "$C_STEP" "$C_RESET" "$BASE"

# ---------- 1. backend liveness ----------

step "1. Backend health"
curl -sf "$BASE/health" >/dev/null \
    || fail "backend not reachable at $BASE/health"
ok "backend is up"

READYZ=$(curl -s "$BASE/readyz")
# /readyz returns structured per-dependency checks: .checks.database.status
DB_STATUS=$(echo "$READYZ" | jq -r '.checks.database.status')
[[ "$DB_STATUS" == "ok" ]] \
    || fail "database not ready (db=$DB_STATUS)"
ok "database is ready"

# ---------- 1b. authenticate ----------

step "1b. Authenticate"
[[ -n "$SMOKE_PASS" ]] \
    || fail "no password set — export SENTINELAI_PASSWORD (or BACKEND_BOOTSTRAP_ADMIN_PASSWORD) for user '$SMOKE_USER'"
LOGIN=$(curl -sf -X POST -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$SMOKE_USER" --arg p "$SMOKE_PASS" '{username:$u,password:$p}')" \
    "$API/auth/login") \
    || fail "login failed for '$SMOKE_USER' — is the bootstrap admin created?"
TOKEN=$(echo "$LOGIN" | jq -r '.access_token')
[[ -n "$TOKEN" && "$TOKEN" != "null" ]] \
    || fail "login returned no access_token"
# Reusable auth header for every protected /api/v1 call below.
AUTHZ=(-H "Authorization: Bearer $TOKEN")
ROLE=$(echo "$LOGIN" | jq -r '.user.role')
ok "authenticated as '$SMOKE_USER' (role=$ROLE)"

# ---------- 2. detection model loaded ----------

step "2. Detection model loaded"
MODEL=$(curl -sf "${AUTHZ[@]}" "$API/detection/model")
LOADED=$(echo "$MODEL" | jq -r '.loaded')
[[ "$LOADED" == "true" ]] \
    || fail "detection model not loaded — run: python -m ml.train --synthetic 50000 && docker compose restart backend"
MODEL_NAME=$(echo "$MODEL" | jq -r '.name')
MODEL_VERSION=$(echo "$MODEL" | jq -r '.version')
ok "model loaded: $MODEL_NAME@$MODEL_VERSION"
note "$(echo "$MODEL" | jq -r '.classes | join(" · ")')"

# ---------- 3. ingest the bundled sample CSV ----------

step "3. Ingest bundled sample CSV"
INGEST=$(curl -sf -X POST "${AUTHZ[@]}" -H 'Content-Type: application/json' \
    -d '{"file":"samples/sample_flows.csv","rate":50}' \
    "$API/ingest/replay")
JOB_ID=$(echo "$INGEST" | jq -r '.job_id')
TOTAL=$(echo "$INGEST" | jq -r '.total_rows')
VALID=$(echo "$INGEST" | jq -r '.valid_rows')
INVALID=$(echo "$INGEST" | jq -r '.invalid_rows')
[[ "$VALID" -gt 0 ]] \
    || fail "no valid rows ingested (total=$TOTAL, invalid=$INVALID)"
ok "ingested job #$JOB_ID: $VALID valid / $INVALID invalid / $TOTAL total"

# ---------- 4. run detection on the freshly-ingested events ----------

step "4. Run detection (auto-triage + auto-respond inline)"
DETECT=$(curl -sf -X POST "${AUTHZ[@]}" -H 'Content-Type: application/json' \
    -d '{"limit":5000}' \
    "$API/detection/run")
PROCESSED=$(echo "$DETECT" | jq -r '.processed')
ALERTS_CREATED=$(echo "$DETECT" | jq -r '.alerts_created')
BENIGN=$(echo "$DETECT" | jq -r '.benign_count')
[[ "$PROCESSED" -gt 0 ]] \
    || fail "detection processed 0 events (expected $VALID)"
ok "detection processed $PROCESSED event(s) · $ALERTS_CREATED alert(s) created · $BENIGN benign"
note "by label: $(echo "$DETECT" | jq -cr '.by_label')"

# ---------- 5. dashboard overview reflects the new state ----------

step "5. Dashboard overview"
OV=$(curl -sf "${AUTHZ[@]}" "$API/dashboard/overview")
TOTAL_EVENTS=$(echo "$OV" | jq -r '.total_events')
TOTAL_ALERTS=$(echo "$OV" | jq -r '.alerts.total')
PENDING=$(echo "$OV" | jq -r '.pending_actions')
ok "dashboard: $TOTAL_EVENTS events · $TOTAL_ALERTS alerts · $PENDING pending actions"
note "by_severity: $(echo "$OV" | jq -cr '.alerts.by_severity')"

# ---------- 6. pick an alert and investigate it ----------

step "6. Pick an alert and investigate"
# Prefer HIGH/CRITICAL, fall back to whatever exists.
ALERT_ID=$(curl -sf "${AUTHZ[@]}" "$API/alerts?sort=priority&limit=1" | jq -r '.[0].id // empty')
[[ -n "$ALERT_ID" ]] \
    || fail "no alerts available — detection produced $ALERTS_CREATED alerts"
ok "picked alert #$ALERT_ID"

INV=$(curl -sf -X POST "${AUTHZ[@]}" -H 'Content-Type: application/json' -d '{}' \
    "$API/alerts/$ALERT_ID/investigate")
INV_SUMMARY=$(echo "$INV" | jq -r '.packet.summary' | head -c 100)
INV_RELATED=$(echo "$INV" | jq -r '.packet.statistics.related_alert_count')
ok "investigation generated — $INV_RELATED related alert(s)"
note "summary: ${INV_SUMMARY}..."

# ---------- 7. mark a disposition ----------

step "7. Analyst disposition: CONFIRMED"
curl -sf -X POST "${AUTHZ[@]}" -H 'Content-Type: application/json' \
    -d '{"disposition":"CONFIRMED","analyst_id":"smoke-test","note":"automated smoke test"}' \
    "$API/alerts/$ALERT_ID/disposition" >/dev/null
ok "alert #$ALERT_ID disposition = CONFIRMED"

# ---------- 8. approve one pending response action (if any) ----------

step "8. Approve a pending response action (if any)"
PENDING_ID=$(curl -sf "${AUTHZ[@]}" "$API/response/pending?limit=1" | jq -r '.[0].id // empty')
if [[ -n "$PENDING_ID" ]]; then
    curl -sf -X POST "${AUTHZ[@]}" -H 'Content-Type: application/json' \
        -d '{"analyst_id":"smoke-test","note":"smoke approval"}' \
        "$API/response/$PENDING_ID/approve" >/dev/null
    ok "approved response action #$PENDING_ID"
else
    note "no pending actions — every recommendation auto-executed"
fi

# ---------- 9. generate a per-alert report ----------

step "9. Generate per-alert report"
REPORT=$(curl -sf -X POST "${AUTHZ[@]}" -H 'Content-Type: application/json' -d '{}' \
    "$API/alerts/$ALERT_ID/report")
REPORT_ID=$(echo "$REPORT" | jq -r '.report_id')
TITLE=$(echo "$REPORT" | jq -r '.packet.title')
MD_BYTES=$(echo "$REPORT" | jq -r '.packet.markdown | length')
ok "report #$REPORT_ID: $TITLE ($MD_BYTES bytes of markdown)"

# ---------- 10. daily summary ----------

step "10. Generate daily summary"
DAILY=$(curl -sf -X POST "${AUTHZ[@]}" -H 'Content-Type: application/json' -d '{}' \
    "$API/reports/daily/run")
DAILY_ID=$(echo "$DAILY" | jq -r '.report_id')
DAILY_ALERTS=$(echo "$DAILY" | jq -r '.packet.total_alerts')
ok "daily summary #$DAILY_ID — $DAILY_ALERTS alert(s) covered"

# ---------- 11. audit trail sanity ----------

step "11. Audit trail on alert #$ALERT_ID"
ALERT_DETAIL=$(curl -sf "${AUTHZ[@]}" "$API/alerts/$ALERT_ID")
N_DECISIONS=$(echo "$ALERT_DETAIL" | jq -r '.decisions | length')
N_ACTIONS=$(echo "$ALERT_DETAIL" | jq -r '.actions | length')
AGENTS=$(echo "$ALERT_DETAIL" | jq -r '[.decisions[].agent] | unique | join(", ")')
ok "$N_DECISIONS agent_decisions row(s) · $N_ACTIONS response_action row(s)"
note "agents in the chain: $AGENTS"

# ---------- summary ----------

printf "\n%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n" "$C_OK" "$C_RESET"
printf "%sFull pipeline executed successfully.%s\n" "$C_OK" "$C_RESET"
printf "  · Frontend:     %s\n" "${SENTINELAI_UI_URL:-http://localhost:5173}"
printf "  · Alert detail: %s/alerts/%s\n" "${SENTINELAI_UI_URL:-http://localhost:5173}" "$ALERT_ID"
printf "  · Report:       %s/reports (open #%s)\n" "${SENTINELAI_UI_URL:-http://localhost:5173}" "$REPORT_ID"
printf "  · API docs:     %s/docs\n" "$BASE"
