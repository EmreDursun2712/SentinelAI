# Lab-only real response (authorized lab networks only)

> ⚠️ **Default behavior is fully simulated.** Real response effects are
> impossible unless you explicitly enable LAB mode AND scope it to authorized
> lab subnets. **Never use against production or external targets.**

## The guardrail

Historically every `response_actions` row was forced to `simulated = TRUE` by a
DB CHECK. That binary guard is replaced by a **stronger, mode-aware** one:

```sql
CHECK (simulated = TRUE OR execution_mode = 'LAB')   -- ck_response_actions_simulated_unless_lab
```

A non-simulated (real) row is therefore *structurally impossible* outside
`execution_mode = 'LAB'`. LAB mode is itself gated by config + approval, so the
default install can never produce a real effect.

## Execution modes

| Mode | `simulated` | Effect |
| --- | --- | --- |
| `SIMULATED` (default) | `true` | Records intent only — nothing is contacted. |
| `LAB` | `false` (real) or `true` (mock) | Controlled, allowlisted, reversible lab effect. |

An action becomes `LAB` only when **all** of these hold; otherwise it stays
`SIMULATED`:

1. `lab_response_active` — see config below;
2. it is a network action (`BLOCK_IP`, `RATE_LIMIT`, `ISOLATE_HOST`); and
3. its target IP is inside an allowed lab CIDR.

Informational actions (`NOTIFY_ANALYST`, `CREATE_TICKET`, `ESCALATE`,
`SUPPRESS_ALERT`, …) are always simulated/informational.

## Configuration

| Env | Default | Notes |
| --- | --- | --- |
| `SENTINEL_RESPONSE_MODE` | `simulated` | `simulated` \| `lab` |
| `SENTINEL_RESPONSE_ENABLED` | `false` | Must be `true` for LAB. |
| `SENTINEL_RESPONSE_EXECUTOR` | `simulated` | `simulated` \| `mock_lab` \| `nftables_lab` |
| `SENTINEL_RESPONSE_ALLOWED_CIDRS` | _(empty)_ | **Required for LAB.** Comma-separated lab subnets. |
| `SENTINEL_RESPONSE_MAX_BLOCK_MINUTES` | `60` | Block durations are capped to this. |
| `SENTINEL_RESPONSE_REQUIRE_APPROVAL` | `true` | LAB network actions always require approval. |

`lab_response_active` is true only when enabled **and** mode=lab **and** a lab
executor **and** at least one allowed CIDR. Anything missing → simulated only.
If a LAB action is somehow requested while config is unsafe, the backend
**refuses** to execute it (it never silently runs a real effect).

## Executors

* **SimulatedExecutor** (default) — never contacts anything; nothing to roll back.
* **MockLabExecutor** — runs every guardrail (CIDR allowlist, duration cap,
  rollback bookkeeping, `external_execution_id`, `expires_at`) but performs no
  real action. For tests and safe demos of the LAB path.
* **NftablesLabExecutor** — a real effect on a dedicated, authorized lab host:
  adds/removes the validated target IP to a pre-created nftables set. Safe by
  construction — the IP is parsed with `ipaddress` and commands run via
  `create_subprocess_exec` (argv list, **no shell**), so there is no injection
  surface. Requires the operator to pre-create the table/set/chain (see the
  module docstring). Only selected when `SENTINEL_RESPONSE_EXECUTOR=nftables_lab`.

## Workflow

1. Detection/triage produces recommendations as usual.
2. In LAB mode, an in-scope network action is created `execution_mode=LAB`,
   `simulated=false`, **PENDING** (never auto-executed).
3. An analyst approves via `POST /api/v1/response/{id}/approve` (ANALYST+). The
   executor validates the target against the lab CIDRs and the duration cap, then
   performs the effect and records `external_execution_id`, `expires_at`,
   `rollback_status=AVAILABLE`, and `rollback_payload`. An out-of-scope target is
   rejected with `400`.
4. To revert, `POST /api/v1/response/{id}/rollback` (ANALYST+). It calls the
   executor's `rollback`, sets `rollback_status=ROLLED_BACK` (or `FAILED`), and
   writes an analyst audit row.

Every step is recorded in `agent_decisions`; the dashboard's Response Center and
the alert detail always show the execution mode and whether an action was
simulated or lab-executed.

## Safe demo (MockLabExecutor)

```bash
# Backend env (e.g. .env / compose):
BACKEND_RESPONSE_ENABLED=true
BACKEND_RESPONSE_MODE=lab
BACKEND_RESPONSE_EXECUTOR=mock_lab
BACKEND_RESPONSE_ALLOWED_CIDRS=10.0.0.0/8,192.168.0.0/16
```

Ingest a flow whose source is in an allowed CIDR, run detection, then approve the
resulting `BLOCK_IP` in the Response Center — it executes via the mock lab
executor (no real effect), shows an `external_execution_id`, and offers a
rollback. Leave these env vars unset for the normal, fully-simulated demo.
