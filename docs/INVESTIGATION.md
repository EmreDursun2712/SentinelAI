# Investigation — evidence gathering and summary

When an analyst opens an alert, the Investigation agent queries the
surrounding `network_events` + `alerts` history, builds a timeline,
computes deterministic statistics, and writes the whole packet to
`alert_artifacts` (`kind = INVESTIGATION_PACKET`). The Reporting agent
(Phase 6 next) reads from there.

**No free-text generation.** Every sentence in the summary is derived
from a counted row or a stored column — the analyst can cross-check every
line against the underlying SQL. No hallucination risk.

## What evidence is gathered

For an alert at `t = alert.created_at`:

| Source                | Query                                                                                                       | Default cap                     |
| --------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------- |
| Related flows         | `network_events` where `src_ip = ?` OR `dst_ip = ?` OR `label = prediction`, time in `[t - 60min, t + 60min]` | 200 (configurable)              |
| Related alerts        | `alerts` where `src_ip = ?` OR `dst_ip = ?` OR `prediction = ?`, in last 24 h, excluding the current alert | 50 (configurable)               |
| Feature importance    | Global `feature_importances_` from the loaded RandomForest pipeline                                         | Top 15                          |

Each query asks for `limit + 1` rows so the service can detect truncation
without a second `COUNT(*)`; `packet.truncated = true` surfaces in the API
when caps were hit.

## What gets computed

From the gathered evidence, deterministic statistics:

- `related_event_count`, `related_alert_count`
- `distinct_source_ips`, `distinct_destination_ips`
- `same_src_ip_alert_count`, `same_dst_ip_alert_count`, `same_family_alert_count`
- `first_seen`, `last_seen`, `activity_span_seconds`
- `top_label` (most common label across related flows)
- `top_prediction` (most common prediction across related alerts)

From the statistics, conditional summary bullets (each one fires only when
the supporting fact is true):

| Bullet                                                            | Fires when                                            |
| ----------------------------------------------------------------- | ----------------------------------------------------- |
| `Source X has N other recent alert(s)…`                           | `same_src_ip_alert_count > 0`                         |
| `Source X has no other recent alerts — likely first observation.` | `same_src_ip_alert_count == 0`                        |
| `Target Y has N other recent alert(s)…`                           | `same_dst_ip_alert_count > 0`                         |
| `N other recent alert(s) share the same prediction…`              | `same_family_alert_count > 0`                         |
| `Surrounding alerts mostly predict 'Z' differing from this alert` | majority prediction differs from this alert           |
| `Related flow activity spans …`                                   | at least two related events                           |
| `N distinct source IPs touched this scope…`                       | `distinct_source_ips > 1`                             |
| `N distinct destination IPs touched…`                             | `distinct_destination_ips > 1`                        |
| `Ground-truth labels nearby mostly say 'Z'…`                      | top label differs from the model's prediction         |

A timeline is built by merging events + related alerts on `timestamp`, with
the current alert always anchored in the list (`is_current_alert: true`).

## API

| Method | Path                                          | Purpose                                                |
| ------ | --------------------------------------------- | ------------------------------------------------------ |
| POST   | `/api/v1/alerts/{id}/investigate`             | Run investigation; body `{events_window_minutes?, alerts_window_hours?, max_events?, max_alerts?}` all optional. Persists. |
| POST   | `/api/v1/alerts/{id}/reinvestigate`           | Alias for `/investigate` (kept for compatibility).      |
| GET    | `/api/v1/alerts/{id}/investigation`           | Return the most recent stored packet (no re-run).      |

The response shape (same for POST and GET):

```jsonc
{
  "artifact_id": 17,
  "packet": {
    "alert_id": 42,
    "generated_at": "2026-05-21T08:35:01Z",
    "events_window_minutes": 60,
    "alerts_window_hours": 24,
    "summary": "Investigated alert #42: BruteForce from 203.0.113.7 to 10.0.0.10:22 (severity=HIGH, priority=67.0, confidence=0.92). Examined 8 related alert(s) and 12 related flow(s).",
    "summary_bullets": [
      "Source 203.0.113.7 has 8 other recent alert(s) in the lookback window.",
      "Target 10.0.0.10 has 8 other recent alert(s) — multiple attempts against the same host.",
      "8 other recent alert(s) share the same prediction 'BruteForce' — consistent campaign pattern.",
      "Related flow activity spans 8.0 min (2026-05-21 08:23:14 → 2026-05-21 08:31:42 UTC)."
    ],
    "statistics": {
      "related_event_count": 12,
      "related_alert_count": 8,
      "distinct_source_ips": 1,
      "distinct_destination_ips": 1,
      "same_src_ip_alert_count": 8,
      "same_dst_ip_alert_count": 8,
      "same_family_alert_count": 8,
      "first_seen": "2026-05-21T08:23:14Z",
      "last_seen":  "2026-05-21T08:31:42Z",
      "activity_span_seconds": 508.0,
      "top_label": "BruteForce",
      "top_prediction": "BruteForce"
    },
    "related_alerts": [ /* RelatedAlertOut[] */ ],
    "related_events": [ /* RelatedEventOut[] */ ],
    "timeline": [
      { "timestamp": "…", "kind": "event", "summary": "Flow 203.0.113.7:38821 → 10.0.0.10:22 (TCP) label=BruteForce" },
      { "timestamp": "…", "kind": "alert", "summary": "Alert #41 BruteForce (HIGH) from 203.0.113.7", "alert_id": 41 },
      { "timestamp": "…", "kind": "alert", "summary": "▶ This alert: #42 BruteForce from 203.0.113.7 to 10.0.0.10:22", "is_current_alert": true }
    ],
    "feature_importance": [
      { "feature": "flow_packets/s", "importance": 0.18 },
      { "feature": "flow_bytes/s",   "importance": 0.16 }
    ],
    "model_name": "sentinelai-detection",
    "model_version": "v20260521-073940",
    "truncated": false
  }
}
```

## Storage contract

Each call creates a new `alert_artifacts` row:

```jsonc
{
  "alert_id": 42,
  "kind": "INVESTIGATION_PACKET",
  "data": { /* InvestigationPacket */ },
  "file_path": null,
  "created_at": "..."
}
```

Calling `/investigate` repeatedly **appends** packets so the history is
preserved (analyst can compare across re-runs after rule updates).
`GET /investigation` returns the most recent one.

Each call also writes one `agent_decisions` row with `agent=INVESTIGATION`:

```jsonc
{
  "decision": {
    "artifact_id": 17, "summary": "…",
    "n_related_events": 12, "n_related_alerts": 8, "truncated": false
  },
  "reasoning": {
    "events_window_minutes": 60, "alerts_window_hours": 24,
    "max_events": 200, "max_alerts": 50,
    "bullets": [ /* same as packet.summary_bullets */ ]
  }
}
```

Alert workflow transition: `status` advances to `INVESTIGATED` (only when it
is currently `NEW`/`TRIAGED`/`AUTO_RESPONDED`/`AWAITING_ANALYST` — never
regresses past `REPORTED`/`CLOSED`). `investigated_at` is stamped on the
alert.

## Demo flow (extends the Response demo)

```bash
# 1. Ingest + run the full chain (Detection → Triage → Response is automatic)
curl -s -X POST -F 'file=@backend/data/samples/sample_flows.csv' \
     http://localhost:8000/api/v1/ingest/upload | jq
curl -s -X POST -H 'Content-Type: application/json' \
     http://localhost:8000/api/v1/detection/run -d '{"limit": 1000}' | jq

# 2. Pick a CRITICAL/HIGH alert and investigate it
ALERT_ID=$(curl -s "http://localhost:8000/api/v1/alerts?severity=HIGH&limit=1" | jq -r '.[0].id')

curl -s -X POST http://localhost:8000/api/v1/alerts/${ALERT_ID}/investigate \
     -H 'Content-Type: application/json' \
     -d '{"events_window_minutes": 120, "alerts_window_hours": 48}' | jq

# 3. Read just the summary
curl -s http://localhost:8000/api/v1/alerts/${ALERT_ID}/investigation \
   | jq '{summary: .packet.summary, bullets: .packet.summary_bullets, stats: .packet.statistics}'

# 4. Inspect the timeline
curl -s http://localhost:8000/api/v1/alerts/${ALERT_ID}/investigation \
   | jq '.packet.timeline[] | {timestamp, kind, summary}'

# 5. Confirm the alert advanced + the artifact was created
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  SELECT id, status, investigated_at FROM alerts WHERE id = ${ALERT_ID};
"
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  SELECT id, alert_id, kind, jsonb_object_keys(data) AS data_key
  FROM alert_artifacts WHERE alert_id = ${ALERT_ID};
"

# 6. Re-investigate after some time — a fresh packet appears
curl -s -X POST http://localhost:8000/api/v1/alerts/${ALERT_ID}/investigate | jq '.artifact_id'
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  SELECT id, created_at FROM alert_artifacts WHERE alert_id = ${ALERT_ID} ORDER BY id;
"
```

## Notes & assumptions

- **On-demand, not automatic.** The Detection chain doesn't auto-investigate
  because the queries scan multiple tables and would slow batch detection.
  The frontend Alert Detail page calls `/investigate` when an analyst opens
  an alert; the result is cached as an artifact so re-opens are free via
  `GET /investigation`.
- **Determinism over flair.** The summary is built from counts — same inputs
  produce identical output strings. There is no LLM in the path.
- **Truncation is reported, not silent.** If the result hit `max_events` or
  `max_alerts`, `packet.truncated = true`. Operators can raise the caps in
  the request body.
- **Feature importance is global, not per-prediction.** SHAP/LIME would be
  more useful per-alert but adds a heavy dep; the global RF importances are
  cheap and still informative. Easy to swap in SHAP later by extending
  `_feature_importance` without changing the API.
- **Cross-checks the model.** When ground-truth `label` columns disagree with
  the model's prediction in nearby flows, the summary surfaces a "possible
  mismatch worth reviewing" bullet — useful for catching drift on a
  CIC-IDS2017 replay where labels are known.
- **Append-only history.** Each `/investigate` call creates a new artifact.
  No mutation, no deletion. The Reporting agent (Phase 6) will read the
  latest one.
