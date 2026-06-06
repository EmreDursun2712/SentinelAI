# Ingestion — CSV schema

SentinelAI accepts network flow records via CSV. The parser is forgiving about
column names, value formatting, and missing optional fields; it is strict about
the small set of fields needed for the detection workflow.

## Required columns

| Canonical key | Accepted CSV headers (case-insensitive)               | Notes                                                                 |
| ------------- | ----------------------------------------------------- | --------------------------------------------------------------------- |
| `event_time`  | `Timestamp`, `Time`, `event_time`                     | ISO 8601 preferred. Falls back to `dd/mm/yyyy hh:mm[:ss]` and `mm/dd/yyyy hh:mm[:ss]`. Naive timestamps are interpreted as UTC. |
| `src_ip`      | `Source IP`, `Src IP`, `src_ip`, `source_ip`          | IPv4 or IPv6.                                                         |
| `dst_ip`      | `Destination IP`, `Dst IP`, `dst_ip`, `destination_ip`| IPv4 or IPv6.                                                         |

## Optional columns (lifted onto the event row)

| Canonical key | Accepted CSV headers                                  | Notes                                                                   |
| ------------- | ----------------------------------------------------- | ----------------------------------------------------------------------- |
| `src_port`    | `Source Port`, `Src Port`, `src_port`, `source_port`  | Integer 0–65535; tolerates `"80.0"`.                                    |
| `dst_port`    | `Destination Port`, `Dst Port`, `dst_port`, `destination_port` | Integer 0–65535.                                                |
| `protocol`    | `Protocol`, `Proto`                                   | Strings (`TCP`, `UDP`, `ICMP`, …) or IANA numbers (`6`, `17`, `1`, …).  |
| `label`       | `Label`, `Class`                                      | Ground-truth attack family (e.g. `BENIGN`, `DDoS`, `BruteForce`).       |

## Feature columns (any extra header)

Every column that isn't in the table above is normalized to `snake_case`,
attempted as a float, and stored in `network_events.features` (JSONB). Empty
cells and `NaN`/`Infinity` sentinels are dropped.

Example: `Total Fwd Packets` → `features["total_fwd_packets"] = 12.0`.

A flow can carry as many extra columns as you want — the parser does not
require any particular feature set, so the same CSV format works for raw
captures, CIC-IDS2017 slices, and home-grown summaries.

## Sample CSV

A 20-row sample lives at [backend/data/samples/sample_flows.csv](../backend/data/samples/sample_flows.csv).
It uses CIC-IDS2017-style headers (`Timestamp`, `Source IP`, `Source Port`,
`Destination IP`, `Destination Port`, `Protocol`, `Flow Duration`, …, `Label`)
and contains a mix of `BENIGN`, `BruteForce`, `DDoS`, and `PortScan` rows.

Header excerpt:

```csv
Timestamp,Source IP,Source Port,Destination IP,Destination Port,Protocol,Flow Duration,Total Fwd Packets,Total Backward Packets,Total Length of Fwd Packets,Total Length of Bwd Packets,Flow Bytes/s,Flow Packets/s,Fwd Packet Length Mean,Bwd Packet Length Mean,Label
```

## Endpoints

| Method | Path                          | Description                                                              |
| ------ | ----------------------------- | ------------------------------------------------------------------------ |
| POST   | `/api/v1/ingest/upload`       | Multipart `file=@flows.csv`. Synchronous; returns the `IngestionSummary`. |
| POST   | `/api/v1/ingest/replay`       | Body `{file, rate}`. Reads a CSV under `SENTINEL_INGEST_DATA_DIR`.        |
| POST   | `/api/v1/ingest/flow`         | Single JSON record; useful for live producers and tests.                 |
| GET    | `/api/v1/ingest/jobs`         | List recent ingestion jobs.                                              |
| GET    | `/api/v1/ingest/jobs/{id}`    | Single ingestion job detail.                                             |

### Response shape

```json
{
  "job_id": 7,
  "status": "COMPLETED",
  "source": "sample_flows.csv",
  "total_rows": 20,
  "valid_rows": 20,
  "invalid_rows": 0,
  "errors": [],
  "errors_truncated": false
}
```

Up to 50 per-row error messages are returned; beyond that, `errors_truncated`
flips to `true` and only the count survives. Every row failure carries its
1-indexed `row_number` for in-CSV navigation.

## Job lifecycle

```
PENDING (rarely seen — created and flipped within one request)
   → RUNNING
       → COMPLETED  (totals filled in, completed_at set)
       → FAILED     (error_message captured, completed_at set)
```

The job row is committed before processing starts, so a crash during the body
still leaves a visible `FAILED` job (not a phantom). Already-flushed batches
of `network_events` are rolled back on failure; the job is the only durable
artifact.

## Limits & guardrails

- Max upload size: 20 MiB (configurable via `SENTINEL_INGEST_MAX_UPLOAD_BYTES`).
- Replay paths are restricted to `SENTINEL_INGEST_DATA_DIR` (default `data`).
  Absolute paths and `..` traversal are rejected.
- Batch size for bulk insert: 500 rows.
- IPs are stored as Postgres `INET`; ports are constrained to 0–65535.

## Quick demo

```bash
# Upload the bundled sample
curl -X POST -F 'file=@backend/data/samples/sample_flows.csv' \
     http://localhost:8000/api/v1/ingest/upload

# Replay a server-side CSV
curl -X POST -H 'Content-Type: application/json' \
     -d '{"file":"samples/sample_flows.csv","rate":50}' \
     http://localhost:8000/api/v1/ingest/replay

# Ingest a single flow
curl -X POST -H 'Content-Type: application/json' http://localhost:8000/api/v1/ingest/flow \
     -d '{
           "event_time": "2024-01-15T08:23:14Z",
           "src_ip": "192.168.1.50",
           "dst_ip": "10.0.0.10",
           "src_port": 52341,
           "dst_port": 443,
           "protocol": "TCP",
           "label": "BENIGN",
           "features": {"flow_duration": 1450}
         }'

# Inspect jobs
curl http://localhost:8000/api/v1/ingest/jobs | jq
```
