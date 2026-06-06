# Ethics & Safety Statement

SentinelAI is a course project for defensive monitoring. It must not be used to attack systems
or alter infrastructure outside its own container network.

## Hard rules

1. **Simulated response only.** Every `ResponseAction` row is created with `simulated=True`.
   `ResponseAgent.simulated_only` is a class-level constant; flipping it is a code change that
   requires explicit instructor approval.
2. **No outbound integrations.** The codebase ships no client for firewalls, EDR agents, ticketing
   systems, paging services, or chat platforms. Notifications stay inside the dashboard.
3. **No packet capture, no payloads — flow metadata only.** SentinelAI never binds a NIC,
   never runs `tcpdump`/`pcap`, and never reads or stores packet payloads. Besides offline
   CIC-IDS2017 CSVs, an **optional log-tailing sensor** (`sensor/`) can feed *real* flow
   metadata from logs that Zeek/Suricata already produced. It is governed by hard controls:
   - **Disabled by default** — refuses to start unless `SENTINEL_SENSOR_ENABLED=true`.
   - **Authorized scope only** — refuses to run without `SENTINEL_SENSOR_ALLOWED_CIDRS`; every
     flow whose endpoints fall outside those lab subnets is dropped before it is sent.
   - **Metadata only** — it parses the 5-tuple, byte/packet counts, and duration; payload
     fields are never read or stored, and logs print counts, not contents.
   - **Authenticated** — batches require an ANALYST/ADMIN JWT and go through the same RBAC +
     rate limits as every other write.
   - Use only on networks you own or are explicitly authorized to monitor. See
     [LIVE_SENSOR.md](LIVE_SENSOR.md).
4. **No exfiltration.** Reports are written to the local `backend/data/reports/` volume.
5. **Dataset license respected.** The CIC-IDS2017 dataset is downloaded by the developer under
   its existing license terms; raw files are gitignored.

## Auditability

Every state transition (agent step or analyst action) is appended to the `audit_log` table.
Logs are JSON-formatted for downstream review.

## If you find yourself wanting to add a real-action driver

Stop. Open an issue, describe the use case, and get written approval from the course instructor
before any code is merged. Treat this file as a gate, not a comment.
