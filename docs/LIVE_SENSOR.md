# Live-flow sensor (authorized lab networks only)

> ⚠️ **For authorized lab networks only.** Use this only on networks you own or
> are explicitly permitted to monitor. It is **disabled by default** and will
> refuse to run unless you opt in and configure authorized subnets.

## What it is (and is not)

SentinelAI ships an optional **log-tailing sensor** that turns real flow records
into detections. By design it is the *safe* form of "live capture":

| It does | It does NOT |
| --- | --- |
| Read flow **logs** Zeek/Suricata already wrote | Bind a NIC or sniff raw packets |
| Read flow **metadata** (5-tuple, byte/packet counts, duration) | Read or store packet **payloads** |
| Post batches to the backend over HTTP | Contact any third party |
| Run only on explicitly allowed CIDRs | Capture arbitrary networks |

The capture itself is done by **Zeek or Suricata**, which your lab operator
configures and points at an authorized interface. SentinelAI only consumes the
logs those tools produce. There is no `tcpdump`, `pcap`, or NIC-binding code in
this repository.

## Architecture

```
Zeek/Suricata  ──writes──▶  conn.log / eve.json
                                  │  (tail, metadata only)
                                  ▼
                       sentinelai-sensor  ──filter to allowed CIDRs──▶ batch
                                  │  POST /api/v1/ingest/flows (Bearer JWT)
                                  ▼
                            SentinelAI backend ──▶ (optional) detection ──▶ alerts
```

## Modes

| Mode | Input | Behavior |
| --- | --- | --- |
| `zeek` | Zeek `conn.log` (TSV) | Tails, follows new lines. |
| `suricata` | Suricata `eve.json` | Tails; uses `event_type` flow/netflow only. |
| `pcap_replay` | A static flow-log file | Reads once (Zeek/Suricata auto-detected). For demos. |

> `pcap_replay` replays a previously-exported **flow log**, not a raw `.pcap`.
> It exists so you can demo the live path without a running Zeek/Suricata.

## Configuration

| Env | Default | Required | Notes |
| --- | --- | --- | --- |
| `SENTINEL_SENSOR_ENABLED` | `false` | yes | Must be `true`; otherwise the sensor refuses to start. |
| `SENTINEL_SENSOR_MODE` | — | yes | `zeek` \| `suricata` \| `pcap_replay`. |
| `SENTINEL_SENSOR_INPUT_PATH` | — | yes | Path to the flow log. |
| `SENTINEL_SENSOR_ALLOWED_CIDRS` | — | **yes** | Comma-separated lab subnets. Flows with neither endpoint inside are dropped. No CIDRs → nothing is in scope (fail closed). |
| `SENTINEL_SENSOR_API_URL` | — | yes | Backend base URL, e.g. `http://backend:8000`. |
| `SENTINEL_SENSOR_API_TOKEN` | — | yes | JWT for an **ANALYST/ADMIN** user (the batch endpoint is a mutation). |
| `SENTINEL_SENSOR_BATCH_SIZE` | `100` | no | Flows per POST. |
| `SENTINEL_SENSOR_INTERVAL_SECONDS` | `2` | no | Max seconds before flushing a partial batch. |

Field mapping (where available): `event_time, src_ip, dst_ip, src_port,
dst_port, protocol` plus `features`: `flow_duration/duration`, `bytes`,
`packets`, `flow_bytes/s`, `flow_packets/s`, `total_fwd_packets`,
`total_backward_packets`, `total_length_of_fwd_packets`,
`total_length_of_bwd_packets`. Columns the CIC-IDS2017 model expects but the log
lacks are simply absent — the backend's median imputer fills them.

## Safety guarantees (enforced in code)

1. **Off by default** — `SensorConfig.validate()` raises unless `ENABLED=true`.
2. **Scoped** — refuses to run without `ALLOWED_CIDRS`; every flow is checked and
   out-of-scope flows are dropped before posting (`safety.flow_in_scope`).
3. **Metadata only** — parsers read 5-tuple + counters; payload fields are never
   read or stored. Logs print counts, not flow contents.
4. **Authenticated** — batches require an ANALYST/ADMIN JWT; the backend enforces
   RBAC + rate limits on `/api/v1/ingest/flows`.

## Backend endpoints

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| POST | `/api/v1/ingest/flows` | ANALYST+ | Batch ingest `{flows:[FlowRecordIn,…]}` (≤1000). |
| GET | `/api/v1/ingest/sensor/status` | VIEWER+ | Liveness proxy: recent ingest activity + last event time. |

Optional auto-detection: set `SENTINEL_DETECTION_AUTO_RUN_ON_INGEST=true` on the
backend to run detection on freshly-queued events right after each batch
(bounded by `SENTINEL_DETECTION_AUTO_RUN_LIMIT`). Default is off.

## Running it

### Standalone

```bash
cd sensor
pip install -e .
# Get a token for an analyst/admin user:
TOKEN=$(curl -fsS localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"admin","password":"<pw>"}' | jq -r .access_token)

SENTINEL_SENSOR_ENABLED=true \
SENTINEL_SENSOR_MODE=pcap_replay \
SENTINEL_SENSOR_INPUT_PATH=./samples/conn.log \
SENTINEL_SENSOR_ALLOWED_CIDRS=192.168.0.0/16,10.0.0.0/8 \
SENTINEL_SENSOR_API_URL=http://localhost:8000 \
SENTINEL_SENSOR_API_TOKEN="$TOKEN" \
python -m sentinelai_sensor
```

### Docker Compose (profile `sensor`, off by default)

```bash
# Set SENSOR_* in your .env first (ENABLED, ALLOWED_CIDRS, API_TOKEN, LOG_DIR…)
docker compose --profile sensor up sensor
```

The compose service is gated behind the `sensor` profile, so a normal
`docker compose up` never starts it. Even when started it refuses to run unless
`SENSOR_ENABLED=true` and `SENSOR_ALLOWED_CIDRS` are set.

## Tests

```bash
cd sensor && pytest    # parser, scope-filter, config-gate, batching tests (stdlib-only)
```
