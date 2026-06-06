# SentinelAI — Live-flow sensor

> **Authorized lab networks only.** Disabled by default. This service reads flow
> **logs** that Zeek/Suricata already produced (or replays a flow log file). It
> never binds a NIC, never captures raw packets, and never stores payloads.

It converts flow records to backend `FlowRecordIn` and POSTs them in batches to
`/api/v1/ingest/flows`. Full guide: [docs/LIVE_SENSOR.md](../docs/LIVE_SENSOR.md).

## Modes

- `zeek` — tail a Zeek `conn.log` (TSV, follows new lines).
- `suricata` — tail a Suricata `eve.json` (JSON lines; `event_type` flow/netflow).
- `pcap_replay` — replay a static flow-log file once (Zeek or Suricata format,
  auto-detected) for demos.

## Configuration (env)

| Variable | Default | Notes |
| --- | --- | --- |
| `SENTINEL_SENSOR_ENABLED` | `false` | Must be `true` or the sensor refuses to start. |
| `SENTINEL_SENSOR_MODE` | — | `zeek` \| `suricata` \| `pcap_replay` |
| `SENTINEL_SENSOR_INPUT_PATH` | — | Path to the flow log to read. |
| `SENTINEL_SENSOR_ALLOWED_CIDRS` | — | Comma-separated lab subnets. **Required**; flows outside are dropped. |
| `SENTINEL_SENSOR_API_URL` | — | Backend base URL, e.g. `http://backend:8000`. |
| `SENTINEL_SENSOR_API_TOKEN` | — | JWT for an ANALYST/ADMIN user. |
| `SENTINEL_SENSOR_BATCH_SIZE` | `100` | Flows per POST. |
| `SENTINEL_SENSOR_INTERVAL_SECONDS` | `2` | Max seconds before flushing a partial batch. |

## Run

```bash
cd sensor
pip install -e ".[dev]"
SENTINEL_SENSOR_ENABLED=true \
SENTINEL_SENSOR_MODE=pcap_replay \
SENTINEL_SENSOR_INPUT_PATH=./samples/conn.log \
SENTINEL_SENSOR_ALLOWED_CIDRS=192.168.0.0/16,10.0.0.0/8 \
SENTINEL_SENSOR_API_URL=http://localhost:8000 \
SENTINEL_SENSOR_API_TOKEN="$TOKEN" \
python -m sentinelai_sensor

pytest    # parser / safety / config tests (stdlib-only)
```
