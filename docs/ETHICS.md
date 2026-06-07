# Ethics & Safety Statement

SentinelAI is a course project for defensive monitoring. It must not be used to attack systems
or alter infrastructure outside its own container network.

## Hard rules

1. **Simulated by default; real response is lab-only and gated.** Actions are `simulated=True`
   unless they are explicit `LAB`-mode actions. The DB CHECK
   `ck_response_actions_simulated_unless_lab` makes a non-simulated row *structurally impossible*
   outside LAB mode. A real LAB effect requires **all** of the following — any one missing keeps
   the action simulated:
   - `SENTINEL_RESPONSE_ENABLED=true`, `SENTINEL_RESPONSE_MODE=lab`, a lab executor
     (`mock_lab`/`nftables_lab`), and `SENTINEL_RESPONSE_ALLOWED_CIDRS` set;
   - the target IP is inside an allowed lab CIDR (out-of-scope targets stay simulated);
   - **analyst approval** — LAB network actions never auto-execute, even at HIGH/CRITICAL;
   - a duration within `SENTINEL_RESPONSE_MAX_BLOCK_MINUTES`;
   - every real action is reversible (`POST /response/{id}/rollback`) and fully audited.

   **No production use.** LAB mode is for an isolated, authorized lab only — never public or
   external targets. See [LAB_RESPONSE.md](LAB_RESPONSE.md).
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
