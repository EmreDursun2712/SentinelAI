# Ethics & Safety Statement

SentinelAI is a course project for defensive monitoring. It must not be used to attack systems
or alter infrastructure outside its own container network.

## Hard rules

1. **Simulated response only.** Every `ResponseAction` row is created with `simulated=True`.
   `ResponseAgent.simulated_only` is a class-level constant; flipping it is a code change that
   requires explicit instructor approval.
2. **No outbound integrations.** The codebase ships no client for firewalls, EDR agents, ticketing
   systems, paging services, or chat platforms. Notifications stay inside the dashboard.
3. **No live packet capture.** Ingestion reads CIC-IDS2017 CSV records from disk. There is no
   `tcpdump`, `pcap`, or NIC-binding code in the repository.
4. **No exfiltration.** Reports are written to the local `backend/data/reports/` volume.
5. **Dataset license respected.** The CIC-IDS2017 dataset is downloaded by the developer under
   its existing license terms; raw files are gitignored.

## Auditability

Every state transition (agent step or analyst action) is appended to the `audit_log` table.
Logs are JSON-formatted for downstream review.

## If you find yourself wanting to add a real-action driver

Stop. Open an issue, describe the use case, and get written approval from the course instructor
before any code is merged. Treat this file as a gate, not a comment.
