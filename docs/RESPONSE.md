# Response — recommendations and the analyst approval loop

The Response agent runs inline after Triage, in the same transaction as
Detection. For each triaged alert it generates a list of **recommendations**:
some are safe enough to auto-execute (notification, ticket creation,
auto-block on HIGH/CRITICAL), others require analyst sign-off through the
Response Center.

**Ethics guardrail.** Every `response_actions` row is created with
`simulated=TRUE`. A `CHECK (simulated = TRUE)` constraint on the table makes
it impossible to insert a row that says otherwise — even via raw SQL. No code
path in this project contacts a firewall, EDR, ticketing system, or anything
outside the container.

## Recommendation policy

Implementation: [backend/app/services/response_rules.py](../backend/app/services/response_rules.py).

| Severity   | Generated recommendations                                                                                  | Approval required for                  |
| ---------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| `CRITICAL` | `BLOCK_IP` (24h), `CREATE_TICKET` (incident), `NOTIFY_ANALYST`. + `ISOLATE_HOST` if family is BruteForce/Infiltration. + `RATE_LIMIT` if DDoS. | None — all auto-execute.               |
| `HIGH`     | `BLOCK_IP` (6h), `CREATE_TICKET` (high), `NOTIFY_ANALYST`. + `RATE_LIMIT` if DDoS.                          | None — all auto-execute.               |
| `MEDIUM`   | `BLOCK_IP` (1h), `ESCALATE`, `NOTIFY_ANALYST`.                                                              | `BLOCK_IP`, `ESCALATE` (NOTIFY auto).  |
| `LOW`      | `NOTIFY_ANALYST`. + `SUPPRESS_ALERT` if `confidence < 0.60`.                                                | `SUPPRESS_ALERT` (NOTIFY auto).        |
| `BENIGN` predicted | `SUPPRESS_ALERT`, `NOTIFY_ANALYST`.                                                                | `SUPPRESS_ALERT`.                      |

Side effects fire **only when an action is executed** (either auto-execute
inline or via `/approve`):

| Action            | Side effect on the alert                                                |
| ----------------- | ----------------------------------------------------------------------- |
| `SUPPRESS_ALERT`  | `disposition = FALSE_POSITIVE`, `status = CLOSED`, `closed_at = now()`. |
| `ESCALATE`        | `disposition = UNDER_REVIEW` (only if currently `OPEN`).                |
| All others        | Informational — the payload is logged, no row state changes.            |

Alert workflow status after a recommendation batch:

- All recommendations auto-executed → `status = AUTO_RESPONDED`
- Any recommendation awaits analyst sign-off → `status = AWAITING_ANALYST`
- Once every pending action is approved or rejected, the alert transitions
  back to `AUTO_RESPONDED` so downstream agents (Investigation, Reporting)
  can pick it up.

## Storage contract

Each generated recommendation becomes one `response_actions` row:

```jsonc
{
  "alert_id": 42,
  "action_type": "BLOCK_IP",
  "simulated": true,           // DB-enforced
  "status": "EXECUTED",        // PENDING | APPROVED | REJECTED | EXECUTED
  "executed": true,
  "approval_required": false,  // auto_execute → false
  "approved_by": null,
  "rejection_reason": null,
  "payload": {
    "rationale": "CRITICAL DDoS from 203.0.113.7 — auto-block.",
    "target_ip": "203.0.113.7",
    "duration": "24h",
    "scope": "perimeter"
  },
  "executed_at": "2026-05-21T08:23:14Z"
}
```

Each batch also writes one `agent_decisions` row with `agent=RESPONSE`
summarizing all recommendations. Analyst approvals/rejections add `agent=ANALYST`
rows so the audit trail under `GET /api/v1/alerts/{id}` shows the complete
chain: `DETECTION → TRIAGE → RESPONSE → ANALYST (approve|reject) → …`.

## API

| Method | Path                                          | Purpose                                                 |
| ------ | --------------------------------------------- | ------------------------------------------------------- |
| GET    | `/api/v1/response`                            | List actions. Filters: `alert_id`, `status`, `action_type`. |
| GET    | `/api/v1/response/pending`                    | List PENDING actions (Response Center queue).           |
| GET    | `/api/v1/response/{action_id}`                | Single action detail.                                   |
| POST   | `/api/v1/response/recommend/{alert_id}`       | Manually generate recommendations (idempotent-append).  |
| POST   | `/api/v1/response/{action_id}/approve`        | Simulate-execute; body `{analyst_id?, note?}`.          |
| POST   | `/api/v1/response/{action_id}/reject`         | Reject; body `{reason, analyst_id?}` (reason required). |

The alert detail endpoint (`GET /api/v1/alerts/{id}`) now eager-loads both
`decisions` and `actions`, so the dashboard's Alert Detail page can render the
full chain in one round trip.

### Example payloads

**Pending queue for the Response Center:**

```bash
curl -s http://localhost:8000/api/v1/response/pending | jq
```

**Approve a pending BLOCK_IP recommendation:**

```bash
curl -s -X POST http://localhost:8000/api/v1/response/7/approve \
     -H 'Content-Type: application/json' \
     -d '{"analyst_id": "alice", "note": "Confirmed brute-force pattern"}' | jq
# → ResponseActionOut: status=EXECUTED, executed=true, executed_at=now,
#   approved_by="alice"
```

**Reject with a reason:**

```bash
curl -s -X POST http://localhost:8000/api/v1/response/8/reject \
     -H 'Content-Type: application/json' \
     -d '{"analyst_id": "alice", "reason": "Allowed scanner, ignore."}' | jq
# → status=REJECTED, rejection_reason="Allowed scanner, ignore."
```

**Manual re-recommend (after a rule update):**

```bash
curl -s -X POST http://localhost:8000/api/v1/response/recommend/42 | jq
# → { "alert_id": 42, "actions": [ResponseActionOut, ...] }
```

## Demo flow (extends the Triage demo)

```bash
# 1. Make sure the stack is up + migrated
docker compose up -d --build
docker compose exec backend alembic upgrade head     # runs through 0004

# 2. Train + load model
python -m ml.train --synthetic 50000
docker compose restart backend

# 3. Ingest + detect — Detection → Triage → Response all run inline
curl -s -X POST -F 'file=@backend/data/samples/sample_flows.csv' \
     http://localhost:8000/api/v1/ingest/upload | jq
curl -s -X POST -H 'Content-Type: application/json' \
     http://localhost:8000/api/v1/detection/run -d '{"limit": 1000}' | jq

# 4. Look at the Response Center queue
curl -s http://localhost:8000/api/v1/response/pending | jq \
  '[.[] | {id, alert_id, action_type, approval_required, "rationale": .payload.rationale}]'

# 5. Inspect a CRITICAL alert's full chain
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  SELECT id, severity, ROUND(priority::numeric, 1) AS pri, status, disposition
  FROM alerts WHERE severity = 'CRITICAL' ORDER BY priority DESC LIMIT 5;
"
curl -s http://localhost:8000/api/v1/alerts/1 | jq \
  '{id, severity, status, disposition,
    decisions: [.decisions[].agent],
    actions:   [.actions[]   | {action_type, status, approval_required}]}'

# 6. Approve a pending BLOCK_IP (MEDIUM-severity alert)
PENDING_ID=$(curl -s http://localhost:8000/api/v1/response/pending \
              | jq -r '.[] | select(.action_type=="BLOCK_IP") | .id' | head -n1)
curl -s -X POST http://localhost:8000/api/v1/response/${PENDING_ID}/approve \
     -H 'Content-Type: application/json' \
     -d '{"analyst_id":"alice","note":"Confirmed: real attack pattern"}' | jq

# 7. Reject a SUPPRESS recommendation with a reason
SUPPRESS_ID=$(curl -s http://localhost:8000/api/v1/response/pending \
               | jq -r '.[] | select(.action_type=="SUPPRESS_ALERT") | .id' | head -n1)
[ -n "$SUPPRESS_ID" ] && curl -s -X POST http://localhost:8000/api/v1/response/${SUPPRESS_ID}/reject \
     -H 'Content-Type: application/json' \
     -d '{"analyst_id":"alice","reason":"Keep this alert — pattern matches recent campaign."}' | jq

# 8. Verify the audit trail captures everyone
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  SELECT alert_id, agent, decision->>'verb' AS verb, decision->>'action_type' AS type
  FROM agent_decisions ORDER BY id DESC LIMIT 15;
"
```

## Notes & assumptions

- **Approval-required vs auto-execute** is a per-rule decision, not a hard
  function of severity alone. `SUPPRESS_ALERT` and `ESCALATE` always require
  approval (they change alert state). `NOTIFY_ANALYST` and `CREATE_TICKET`
  always auto-execute (they're informational). `BLOCK_IP`/`RATE_LIMIT`/
  `ISOLATE_HOST` auto-execute for HIGH/CRITICAL and require approval for
  MEDIUM and below.
- **No deduplication** — calling `/recommend/{id}` twice creates two batches.
  Analysts can see the history. Useful for "re-recommend after rule update."
- **Recommendation is `frozen=True`** — once the engine produces them, the
  service consumes them as immutable values before they ever touch the DB.
- **Alert status state machine** is well-defined: `AWAITING_ANALYST` requires
  at least one PENDING action; once every PENDING action is resolved, the
  alert auto-advances back to `AUTO_RESPONDED`. Status never regresses past
  `INVESTIGATED`/`REPORTED`/`CLOSED`.
- **Side-effect logic is centralized** in `_simulate_execute()` so the auto-
  execute path and the analyst-approval path behave identically.
- **No external integrations.** When you see `payload.target_ip` or
  `payload.ticket_id` in a row, that is the data that *would* be sent to a
  firewall or ticketing system if one were wired up. Nothing is.
