#!/usr/bin/env bash
# Pre-populate SentinelAI with realistic alerts, analyst actions, and reports
# so that opening the dashboard for the first time shows a "live SOC"
# instead of empty cards.
#
# Runs after the stack is up and the model is loaded (i.e. after
# `make bootstrap`). Idempotent in spirit — re-running just ingests the
# bundled sample again and adds more alerts. Use `make reset && make demo`
# for a perfectly clean state.
#
# What it does, in order:
#   1. Replay backend/data/samples/sample_flows.csv (~60 flows).
#   2. Run detection on the freshly-ingested events.
#   3. Pick a HIGH/CRITICAL alert and:
#        - mark it CONFIRMED
#        - run an investigation packet against it
#        - generate a per-alert markdown report
#   4. Pick a different alert and mark it UNDER_REVIEW.
#   5. Approve one pending response action; reject another with a reason.
#   6. Generate today's DAILY_SUMMARY report.
#
# Honors $SENTINELAI_BASE_URL (default http://localhost:8000).

set -euo pipefail

BASE="${SENTINELAI_BASE_URL:-http://localhost:8000}"
API="$BASE/api/v1"

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

require_cmd() { command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"; }
require_cmd curl
require_cmd jq

printf "%sSentinelAI demo seed%s — target: %s\n" "$C_STEP" "$C_RESET" "$BASE"

# ---------- preflight ----------

curl -fsS "$BASE/health" >/dev/null \
    || fail "backend not reachable — run \`make bootstrap\` first"
MODEL_LOADED=$(curl -fsS "$API/detection/model" | jq -r '.loaded')
[[ "$MODEL_LOADED" == "true" ]] \
    || fail "detection model not loaded — run \`make seed\` first"
ok "stack is healthy and a model is loaded"

# ---------- 1. ingest ----------

step "1. Ingest bundled sample CSV"
INGEST=$(curl -fsS -X POST -H 'Content-Type: application/json' \
    -d '{"file":"samples/sample_flows.csv","rate":50}' \
    "$API/ingest/replay")
VALID=$(echo "$INGEST" | jq -r '.valid_rows')
TOTAL=$(echo "$INGEST" | jq -r '.total_rows')
[[ "$VALID" -gt 0 ]] || fail "no valid rows ingested"
ok "ingested $VALID / $TOTAL row(s)"

# ---------- 2. detection ----------

step "2. Run detection"
DETECT=$(curl -fsS -X POST -H 'Content-Type: application/json' \
    -d '{"limit":5000}' "$API/detection/run")
PROCESSED=$(echo "$DETECT" | jq -r '.processed')
ALERTS=$(echo "$DETECT" | jq -r '.alerts_created')
ok "processed $PROCESSED event(s), $ALERTS alert(s) created"
note "by label: $(echo "$DETECT" | jq -cr '.by_label')"

# ---------- 3. flagship alert: confirm + investigate + report ----------

step "3. Hero alert — confirm + investigate + report"
TOP_ID=$(curl -fsS "$API/alerts?sort=priority&limit=1" | jq -r '.[0].id // empty')
[[ -n "$TOP_ID" ]] || fail "no alerts produced — model may be misclassifying"
note "top alert: #$TOP_ID"

curl -fsS -X POST -H 'Content-Type: application/json' \
    -d '{"disposition":"CONFIRMED","analyst_id":"demo-seed","note":"Confirmed by pre-demo seed script."}' \
    "$API/alerts/$TOP_ID/disposition" >/dev/null
ok "alert #$TOP_ID disposition = CONFIRMED"

curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' \
    "$API/alerts/$TOP_ID/investigate" >/dev/null
ok "investigation packet generated for #$TOP_ID"

REPORT=$(curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' \
    "$API/alerts/$TOP_ID/report")
REPORT_ID=$(echo "$REPORT" | jq -r '.report_id')
ok "report #$REPORT_ID generated for #$TOP_ID"

# ---------- 4. second alert: under review ----------

step "4. Second alert — mark UNDER_REVIEW"
# Pick the second-highest-priority alert that isn't the hero.
SECOND_ID=$(curl -fsS "$API/alerts?sort=priority&limit=5" \
    | jq -r ".[] | select(.id != $TOP_ID) | .id" | head -n 1)
if [[ -n "$SECOND_ID" ]]; then
    curl -fsS -X POST -H 'Content-Type: application/json' \
        -d '{"disposition":"UNDER_REVIEW","analyst_id":"demo-seed","note":"Triaging — needs more context."}' \
        "$API/alerts/$SECOND_ID/disposition" >/dev/null
    ok "alert #$SECOND_ID disposition = UNDER_REVIEW"
else
    note "only one alert exists — skipping"
fi

# ---------- 5. response actions: approve one, reject another ----------

step "5. Response queue — approve + reject"
PENDING_IDS=$(curl -fsS "$API/response/pending?limit=10" | jq -r '.[].id')
APPROVED_COUNT=0
REJECTED_COUNT=0
PENDING_ARRAY=()
while IFS= read -r line; do
    [[ -n "$line" ]] && PENDING_ARRAY+=("$line")
done <<< "$PENDING_IDS"

if [[ "${#PENDING_ARRAY[@]}" -ge 1 ]]; then
    curl -fsS -X POST -H 'Content-Type: application/json' \
        -d '{"analyst_id":"demo-seed","note":"Approved by demo seed."}' \
        "$API/response/${PENDING_ARRAY[0]}/approve" >/dev/null \
        && APPROVED_COUNT=1
    ok "approved response action #${PENDING_ARRAY[0]}"
fi
if [[ "${#PENDING_ARRAY[@]}" -ge 2 ]]; then
    curl -fsS -X POST -H 'Content-Type: application/json' \
        -d '{"analyst_id":"demo-seed","reason":"Internal scanner, not a real threat."}' \
        "$API/response/${PENDING_ARRAY[1]}/reject" >/dev/null \
        && REJECTED_COUNT=1
    ok "rejected response action #${PENDING_ARRAY[1]}"
fi
if [[ "$APPROVED_COUNT" -eq 0 && "$REJECTED_COUNT" -eq 0 ]]; then
    note "no pending actions — every recommendation auto-executed"
fi

# ---------- 6. daily summary ----------

step "6. Daily summary report"
DAILY=$(curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' \
    "$API/reports/daily/run")
DAILY_ID=$(echo "$DAILY" | jq -r '.report_id')
DAILY_ALERTS=$(echo "$DAILY" | jq -r '.packet.total_alerts')
ok "daily summary #$DAILY_ID covers $DAILY_ALERTS alert(s)"

# ---------- summary ----------

printf "\n%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n" \
    "$C_OK" "$C_RESET"
printf "%sDashboard is now seeded.%s Open: %s\n" \
    "$C_OK" "$C_RESET" "${SENTINELAI_UI_URL:-http://localhost:5173}"
printf "  · Hero alert (CONFIRMED, with report):  /alerts/%s\n" "$TOP_ID"
[[ -n "${SECOND_ID:-}" ]] && \
    printf "  · Second alert (UNDER_REVIEW):          /alerts/%s\n" "$SECOND_ID"
printf "  · Reports page (with daily summary):    /reports\n"
printf "  · Response Center:                      /response\n"
