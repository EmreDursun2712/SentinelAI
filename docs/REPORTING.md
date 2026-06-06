# Reporting — incident reports and daily summaries

The Reporting agent produces two flavors of structured report, both persisted
to the existing `incident_reports` table:

| Kind            | Trigger                                      | Source data                                                                |
| --------------- | -------------------------------------------- | -------------------------------------------------------------------------- |
| `PER_ALERT`     | `POST /api/v1/alerts/{id}/report`            | `alerts`, `agent_decisions`, `response_actions`, latest `INVESTIGATION_PACKET` |
| `DAILY_SUMMARY` | `POST /api/v1/reports/daily/run`             | `alerts` + `response_actions` aggregates over a 24h UTC window             |

**Evidence-based, no free-text generation.** Every sentence in the report
maps to a counted row or a stored column. No LLM in the path; the renderer
is plain Python string formatting with table escaping.

Each report is stored two ways:

1. **Structured** in `incident_reports.summary` (JSONB) — exactly the
   `AlertReportPacket` / `DailySummaryPacket` shape returned by the API.
2. **Markdown** — both **inline** as `summary["markdown"]` and on disk at
   `<reports_dir>/report-{id}.md` (best-effort; failure to write the file
   doesn't fail the request).

## Per-alert report structure

Eight sections, in fixed order:

| # | Section                  | Source                                                                |
| - | ------------------------ | --------------------------------------------------------------------- |
| 1 | Incident Overview        | `alerts` row + `model_versions` join                                  |
| 2 | Severity & Priority      | `agent_decisions(TRIAGE).reasoning.factors / explanations`            |
| 3 | Detection Results        | `agent_decisions(DETECTION).decision / reasoning.class_probabilities` |
| 4 | Investigation Findings   | Most recent `alert_artifacts(INVESTIGATION_PACKET)`                   |
| 5 | Timeline                 | Investigation timeline + synthesized agent rows                       |
| 6 | Response Recommendations | `response_actions` rows                                               |
| 7 | Analyst Action Status    | `alerts.status` + `disposition` + `agent_decisions(ANALYST)` rows     |
| 8 | Final Summary            | Synthesized from the above (deterministic template)                   |

If any source is missing (e.g. no investigation packet, no triage decision),
the corresponding section renders an explicit "_None recorded_" note rather
than fabricating content.

## Daily summary structure

| Section                             | What it shows                                                |
| ----------------------------------- | ------------------------------------------------------------ |
| Totals                              | `total_alerts`, `response_actions_total`                     |
| By severity / status / disposition  | Three count tables                                           |
| Response actions by type / status   | Two count tables                                             |
| Top source IPs (top 10)             | `Alert.src_ip GROUP BY count`                                |
| Top destination IPs (top 10)        | `Alert.dst_ip GROUP BY count`                                |
| Top predictions (top 10)            | `Alert.prediction GROUP BY count`                            |
| Mean latencies                      | Detection → {Triage, Response, Investigation, Report} mean s |
| Summary                             | One-paragraph synthesis                                      |

Latency rows where the stage hasn't been reached for any alert in the period
render as `—` rather than `0.00`.

## API

| Method | Path                                  | Purpose                                              |
| ------ | ------------------------------------- | ---------------------------------------------------- |
| POST   | `/api/v1/alerts/{id}/report`          | Generate (and persist) a per-alert incident report   |
| GET    | `/api/v1/alerts/{id}/report`          | Return the most recent per-alert report              |
| GET    | `/api/v1/reports`                     | List reports. Filters: `kind`, `alert_id`, `limit`, `offset` |
| GET    | `/api/v1/reports/{id}`                | Return the full structured packet (incl. markdown)   |
| GET    | `/api/v1/reports/{id}/markdown`       | Raw markdown (`text/markdown; charset=utf-8`)        |
| POST   | `/api/v1/reports/daily/run`           | Generate a daily summary; body: `{date?}` (UTC)      |

### Example payloads

**Per-alert report (response shape):**

```jsonc
{
  "report_id": 17,
  "packet": {
    "alert_id": 42, "report_id": 17, "kind": "PER_ALERT",
    "title": "Incident Report — Alert #42 (BruteForce)",
    "generated_at": "...",
    "workflow_status": "REPORTED", "disposition": "UNDER_REVIEW",
    "overview": { /* OverviewSection */ },
    "severity_priority": { /* SeverityPrioritySection */ },
    "detection": { /* DetectionSection */ },
    "investigation": { "available": true, /* … */ },
    "timeline": { "items": [ /* TimelineRow[] */ ] },
    "response": { "actions": [ /* ResponseActionRow[] */ ],
                  "auto_executed": 3, "awaiting_approval": 0, "rejected": 0 },
    "analyst": { "status": "REPORTED", "disposition": "UNDER_REVIEW",
                 "entries": [ /* AnalystEntry[] */ ] },
    "final_summary": "Alert #42 was classified as **BruteForce** with 0.92 confidence by `sentinelai-detection@v...` …",
    "markdown": "# Incident Report — Alert #42 (BruteForce)\n\n…"
  }
}
```

**Daily summary:**

```bash
curl -s -X POST http://localhost:8000/api/v1/reports/daily/run \
     -H 'Content-Type: application/json' -d '{"date":"2026-05-21"}' | jq
```

## Side effects on the alert

A successful `POST /alerts/{id}/report`:

- Stamps `alerts.reported_at = now()`.
- Advances `alerts.status` to `REPORTED` if currently in `NEW`/`TRIAGED`/
  `AUTO_RESPONDED`/`AWAITING_ANALYST`/`INVESTIGATED`. Never regresses
  past `CLOSED`.
- Writes one `agent_decisions` row with `agent=REPORTING` referencing the
  new `report_id`, section list, and disk path.

Daily summaries don't touch alerts — they only insert into `incident_reports`.

## Configuration

| Env var                        | Default          | Purpose                                |
| ------------------------------ | ---------------- | -------------------------------------- |
| `SENTINEL_REPORTS_DIR`         | `data/reports`   | Where the per-report markdown lands on disk |

`data/reports/` ships gitignored. In Docker the path resolves to
`/app/data/reports/` (the backend container's working directory is `/app`).
Locally, when running uvicorn from `backend/`, the same relative path
resolves to `backend/data/reports/`.

## Demo flow (end-to-end across all six phases)

```bash
# Phase 1 — bring up the stack
docker compose up -d --build
docker compose exec backend alembic upgrade head     # → 0004

# Phase 2 — train + load model
python -m ml.train --synthetic 50000
docker compose restart backend

# Phase 3 — ingest the bundled sample
curl -s -X POST -F 'file=@backend/data/samples/sample_flows.csv' \
     http://localhost:8000/api/v1/ingest/upload | jq

# Phase 3+4 — detection auto-triages + auto-responds inline
curl -s -X POST -H 'Content-Type: application/json' \
     http://localhost:8000/api/v1/detection/run -d '{"limit": 1000}' | jq

# Phase 5 — pick a HIGH alert and run investigation
ALERT_ID=$(curl -s "http://localhost:8000/api/v1/alerts?severity=HIGH&limit=1" | jq -r '.[0].id')
curl -s -X POST http://localhost:8000/api/v1/alerts/${ALERT_ID}/investigate | jq '.packet.summary'

# Phase 6 — generate the per-alert incident report
curl -s -X POST http://localhost:8000/api/v1/alerts/${ALERT_ID}/report \
   | jq '{report_id, title: .packet.title, sections: (.packet | keys)}'

# Read the rendered markdown directly
REPORT_ID=$(curl -s http://localhost:8000/api/v1/alerts/${ALERT_ID}/report | jq -r '.report_id')
curl -s http://localhost:8000/api/v1/reports/${REPORT_ID}/markdown

# Confirm the markdown also landed on disk
docker compose exec backend ls -la /app/data/reports/

# Daily summary for today
curl -s -X POST http://localhost:8000/api/v1/reports/daily/run | jq '.packet | {date, total_alerts, by_severity, response_actions_total}'

# List the reports we just created
curl -s "http://localhost:8000/api/v1/reports?limit=10" | jq

# Audit chain on the alert
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  SELECT agent, decision->>'report_id' AS report_id, decision->>'title' AS title
  FROM agent_decisions
  WHERE alert_id = ${ALERT_ID} ORDER BY id;
"

# Workflow status reached REPORTED
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  SELECT id, status, disposition, reported_at FROM alerts WHERE id = ${ALERT_ID};
"
```

## Notes & assumptions

- **Append-only history.** Calling `/report` twice creates two reports.
  `GET /alerts/{id}/report` returns the most recent. Useful for "regenerate
  after rule update" without erasing the previous version.
- **Markdown over PDF.** WeasyPrint (the architecture's original PDF
  candidate) adds C deps for a feature only the final demo needs. Markdown
  is renderable in any browser and copy-pastes into Slack/Confluence cleanly;
  PDF can be a one-line `pandoc` post-step on the operator's side.
- **Determinism check in tests.** `test_alert_markdown_is_deterministic`
  renders the same packet twice and asserts byte-equal output.
- **Table-safe escaping.** All cell values go through `_md_cell` which
  escapes pipes and collapses newlines so a payload field can't break the
  markdown table.
- **No new migration.** The `incident_reports` table and its `kind` enum
  (`PER_ALERT` / `DAILY_SUMMARY`) shipped in Phase 1; the packet shape lives
  entirely in the JSONB `summary` column.
- **27-case test suite** at [backend/tests/test_reporting.py](../backend/tests/test_reporting.py)
  covers cell escaping, every section builder, both markdown renderers, and
  graceful-degradation paths for missing detection / investigation /
  response data.
