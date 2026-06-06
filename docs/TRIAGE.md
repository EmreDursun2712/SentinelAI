# Triage — severity, priority, and the analyst feedback loop

The Triage agent runs immediately after Detection creates an alert. It computes
a **priority score (0–100)** from four explainable components, maps that to a
**severity tier (LOW / MEDIUM / HIGH / CRITICAL)**, and writes both an updated
`alerts` row and an `agent_decisions` audit entry — all inside the same
transaction Detection started, so dashboards never see a half-triaged alert.

Analyst feedback is captured through a separate dimension, **disposition**,
that runs OPEN → UNDER_REVIEW → {CONFIRMED | FALSE_POSITIVE | RESOLVED}.
This is deliberately orthogonal to the agent-workflow `status` so we can
distinguish "where the alert is in the pipeline" from "what the human thinks
about it."

## Two dimensions, never confused

| Dimension     | Driven by         | Values                                                                              |
| ------------- | ----------------- | ----------------------------------------------------------------------------------- |
| `status`      | Agents            | `NEW`, `TRIAGED`, `AUTO_RESPONDED`, `AWAITING_ANALYST`, `INVESTIGATED`, `REPORTED`, `CLOSED` |
| `disposition` | Analyst (or auto) | `OPEN`, `UNDER_REVIEW`, `CONFIRMED`, `FALSE_POSITIVE`, `RESOLVED`                    |

`FALSE_POSITIVE` and `RESOLVED` are **terminal verdicts** — the triage service
auto-closes the workflow (`status=CLOSED`, `closed_at=now()`) when they fire.

## Rule engine

Implementation: [backend/app/services/triage_rules.py](../backend/app/services/triage_rules.py).

```
priority (0–1) = 0.40 · family
               + 0.30 · confidence
               + 0.20 · port_criticality
               + 0.10 · volume

priority (0–100) = round(priority · 100, 2)
severity         = bucket(priority)
```

| Component       | Range  | Source                                                                                  |
| --------------- | ------ | --------------------------------------------------------------------------------------- |
| `family`        | 0–1    | Lookup in `FAMILY_WEIGHTS` (DDoS=0.85, BruteForce=0.70, Infiltration=1.0, BENIGN=0.0, …). Substring fallback handles CIC-IDS2017 spellings like `"Web Attack – XSS"`. |
| `confidence`    | 0–1    | Model's top-class probability, clamped to `[0, 1]`.                                     |
| `port_criticality` | 0–1 | `PORT_CRITICALITY` lookup. SSH/RDP/DB > HTTP/HTTPS > DNS. Default `0.30` for unknown ports. |
| `volume`        | 0–1    | Bucketed count of alerts from the same `src_ip` in the last 15 minutes.                 |

Severity tiers:

| Priority           | Severity   |
| ------------------ | ---------- |
| `priority ≥ 85`    | `CRITICAL` |
| `60 ≤ priority < 85` | `HIGH`   |
| `30 ≤ priority < 60` | `MEDIUM` |
| `priority < 30`    | `LOW`      |

### What gets stored

Every triage run writes one `agent_decisions` row with `agent=TRIAGE`:

```jsonc
{
  "decision": {
    "severity": "CRITICAL",
    "priority": 85.10,
    "recent_count": 30
  },
  "reasoning": {
    "factors": {
      "family": "DDoS",
      "family_score": 0.85,
      "confidence_score": 0.92,
      "dst_port": 3389,
      "port_score": 0.90,
      "volume_score": 0.55
    },
    "component_weights": {"family": 0.40, "confidence": 0.30, "port": 0.20, "volume": 0.10},
    "explanations": [
      "family=DDoS → criticality 0.85 × 40%",
      "confidence=0.92 → confidence 0.92 × 30%",
      "dst_port=3389 → criticality 0.90 × 20%",
      "recent_src_ip_alerts=30 → volume 0.55 × 10%",
      "priority=85.10 → severity=CRITICAL"
    ],
    "window_minutes": 15
  }
}
```

The full chain (Detection → Triage → Response → analyst → …) appears as
ordered rows in `agent_decisions` for that alert. See [RESPONSE.md](RESPONSE.md)
for what the Response agent does next.

## Disposition (analyst verdict)

| Value             | Meaning                                                                  | Side effect                       |
| ----------------- | ------------------------------------------------------------------------ | --------------------------------- |
| `OPEN`            | Default. No analyst action yet.                                          | None.                             |
| `UNDER_REVIEW`    | Analyst has picked it up.                                                | None.                             |
| `CONFIRMED`       | Real attack — keep flowing through response/investigation.               | None.                             |
| `FALSE_POSITIVE`  | Not actually malicious.                                                  | `status=CLOSED`, `closed_at=now`. |
| `RESOLVED`        | Handled (action taken or no further action needed).                      | `status=CLOSED`, `closed_at=now`. |

Every disposition change writes an `agent_decisions` row with `agent=ANALYST`
so the trail is preserved even when the analyst changes their mind.

## API

| Method | Path                                          | Purpose                                                       |
| ------ | --------------------------------------------- | ------------------------------------------------------------- |
| GET    | `/api/v1/alerts`                              | List with filters: `status`, `severity`, `disposition`, `src_ip`, `dst_ip`, `min_priority`. Sort by `created_at` (default), `priority`, or `severity`. |
| GET    | `/api/v1/alerts/stats`                        | Counts grouped by `status` / `severity` / `disposition`.       |
| GET    | `/api/v1/alerts/{id}`                         | Alert detail with the full `agent_decisions` audit trail.      |
| POST   | `/api/v1/alerts/{id}/triage`                  | Re-run triage; body `{window_minutes?: int}`.                  |
| POST   | `/api/v1/alerts/{id}/disposition`             | Analyst verdict; body `{disposition, note?, analyst_id?}`.     |
| POST   | `/api/v1/alerts/{id}/close`                   | Force-close the workflow.                                      |

### Example payloads

**List filtered by severity, sorted by priority:**

```bash
curl -s "http://localhost:8000/api/v1/alerts?severity=HIGH&sort=priority&limit=20" | jq
```

**Mark an alert as false positive:**

```bash
curl -s -X POST http://localhost:8000/api/v1/alerts/42/disposition \
     -H 'Content-Type: application/json' \
     -d '{
           "disposition": "FALSE_POSITIVE",
           "analyst_id": "alice",
           "note": "Internal scan from approved vulnerability scanner."
         }' | jq
# → AlertOut with disposition=FALSE_POSITIVE, status=CLOSED, closed_at=now
```

**Re-triage after a rule update:**

```bash
curl -s -X POST http://localhost:8000/api/v1/alerts/42/triage \
     -H 'Content-Type: application/json' -d '{"window_minutes": 60}' | jq
# {
#   "alert_id": 42, "severity": "HIGH", "priority": 67.0, "recent_count": 3,
#   "component_weights": {...}, "factors": {...}, "explanations": [...]
# }
```

**Dashboard counters:**

```bash
curl -s http://localhost:8000/api/v1/alerts/stats | jq
# {
#   "total": 137,
#   "by_status":      {"NEW": 0, "TRIAGED": 89, "CLOSED": 48},
#   "by_severity":    {"LOW": 32, "MEDIUM": 41, "HIGH": 51, "CRITICAL": 13},
#   "by_disposition": {"OPEN": 89, "CONFIRMED": 25, "FALSE_POSITIVE": 18, "RESOLVED": 5}
# }
```

## Demo flow (extends the Phase 3 demo)

```bash
# 1. Stack up + migrate
docker compose up -d --build
docker compose exec backend alembic upgrade head     # runs through 0003

# 2. Train + load a model (Phase 2)
python -m ml.train --synthetic 50000
docker compose restart backend

# 3. Ingest + detect (triage runs automatically inside detect_events)
curl -s -X POST -F 'file=@backend/data/samples/sample_flows.csv' \
     http://localhost:8000/api/v1/ingest/upload | jq
curl -s -X POST -H 'Content-Type: application/json' \
     http://localhost:8000/api/v1/detection/run -d '{"limit": 1000}' | jq

# 4. Confirm alerts are TRIAGED with severity + priority
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  SELECT id, prediction, severity, ROUND(priority::numeric, 1) AS priority,
         status, disposition
  FROM alerts ORDER BY priority DESC NULLS LAST LIMIT 10;
"

# 5. Open dashboard view: sort by priority desc
curl -s "http://localhost:8000/api/v1/alerts?sort=priority&limit=10" | jq '.[].priority'

# 6. Inspect a single alert's full decision chain
curl -s http://localhost:8000/api/v1/alerts/1 | jq '.decisions[] | {agent, decision}'

# 7. Analyst marks one as false positive
curl -s -X POST http://localhost:8000/api/v1/alerts/1/disposition \
     -H 'Content-Type: application/json' \
     -d '{"disposition":"FALSE_POSITIVE","analyst_id":"alice","note":"Known internal scan"}' | jq
```
