# Demo Script

A 10-minute classroom walkthrough of the integrated SentinelAI system —
covering ingestion → detection → triage → response → investigation → reporting,
all through the dashboard UI. The end of the document also includes an
automated smoke test (`infra/scripts/smoke_demo.sh`) that exercises the same
path via curl.

Each section ends with the **one sentence to say out loud** so the demo lands
its point.

---

## Prerequisites (one-time, ~3 minutes)

```bash
# 0a. Start the stack
docker compose up -d --build
docker compose exec backend alembic upgrade head

# 0b. Train + stage a model (any synthetic-size works)
python -m ml.train --synthetic 50000

# 0c. Reload the backend so the lifespan picks up the model
docker compose restart backend

# 0d. Install the frontend deps + start dev server
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

Open three browser tabs:

| Tab | URL                                | Why                             |
| --- | ---------------------------------- | ------------------------------- |
| 1   | <http://localhost:5173>            | The dashboard you'll demo from. |
| 2   | <http://localhost:8000/docs>       | OpenAPI surface for the Q&A.    |
| 3   | terminal with `docker compose logs -f backend` | Live structured logs.           |

---

## Step 1 — Dashboard tour (~1 min)

Land on `/`.

- **4 KPI cards**: total events, suspicious events, open alerts, critical alerts.
- **Three charts**: alerts over time (stacked area, 24 h), severity donut,
  top attack categories (horizontal bars).
- **Highest-priority alerts** table on the bottom-left.
- **Model** panel on the bottom-right shows the loaded classifier — name,
  version, threshold, feature count.
- **Topbar pills** (Backend, Database) should both be emerald.

> **Say out loud:** "This is a single page that tells me the state of the
> entire SOC — what's been seen, what's been flagged, what's pending, and
> which model is running."

---

## Step 2 — Ingest data on `/ingestion` (~2 min)

Click **Ingestion** in the sidebar.

The page is a three-step guided workflow:

1. Click **Replay bundled sample** (or drop a CSV).
   - Step 1 turns green: ingestion summary appears (20 rows / 20 valid / 0 invalid).
   - Page auto-scrolls to step 2.
2. Click **Run detection now**.
   - Step 2 turns green: detection summary (processed, alerts created, benign,
     per-label breakdown with the actual attack families found).
   - Page auto-scrolls to step 3.
3. Click **Open Alerts console →**.

> **Say out loud:** "Three button clicks: upload, detect, walk into alerts.
> Detection auto-triages and auto-recommends responses in the same database
> transaction — by the time you land on the Alerts page, severity and priority
> are already set and high-severity actions like BLOCK_IP have already
> auto-executed."

---

## Step 3 — Alerts list on `/alerts` (~1 min)

Sort by priority (high → low) using the dropdown.

- Severity / status / disposition / attack-type filters across the top.
- Search box does an `ILIKE` against `src_ip`, `dst_ip`, `prediction`.
- Pagination at the bottom.

> **Say out loud:** "Every filter is in the URL — bookmarkable, shareable.
> The search runs against Postgres, not just the current page."

Click into one of the HIGH-severity rows.

---

## Step 4 — Alert detail (~3 min)

`/alerts/{id}` is the analyst workhorse. Walk through, top to bottom:

1. **Header** — alert ID, severity / status / disposition pills, src → dst.
2. **Action bar — two rows**:
   - **Disposition quick-actions**: Mark under review · Confirm threat ·
     False positive · Resolve. Click **Mark under review** — pill flips to
     `UNDER_REVIEW` instantly, decision chain at the bottom gains an
     `ANALYST` row.
   - **Workflow**: Re-triage · Run investigation · Generate report · Close.
3. **Detection card** (left) — predicted label, confidence to 4 decimals,
   threshold, model identity, full class-probability table.
4. **Triage card** (right) — severity, priority, recent_count, and the
   explanation lines (`family=BruteForce → criticality 0.70 × 40%`, …).
5. Click **Run investigation**. The Investigation card fills with a
   summary + bullets + 8 statistics tiles + top contributing features.
6. **Related evidence**: two cards appear — related alerts (clickable IDs)
   and related events (chronological flows with their labels).
7. **Response recommendations** table — show the rationale column, point at
   the **Approve / Reject** buttons on PENDING rows. Approve one.
8. **Metadata** + **Decision chain** at the bottom — point out the chronological
   `DETECTION → TRIAGE → RESPONSE → ANALYST(under_review) → INVESTIGATION
   → ANALYST(approve BLOCK_IP)` chain.
9. Click **Generate report**.

> **Say out loud:** "Every state change writes an audit row keyed to the
> alert. Nothing happens 'silently'."

---

## Step 5 — Response Center on `/response` (~1 min)

- **4 KPI cards**: Pending, Auto-executed (24 h), Approved (24 h), Rejected (24 h).
- **Action-type filter** at the top.
- **Pending queue** — each item shows the action badge, the alert ID, the
  rationale on its own line (full width, the most important field per the
  recommendation spec), and Approve / Reject buttons. Click **Show payload**
  on one row to reveal the JSON payload the response would carry to a real
  firewall.
- **Simulated action execution history** table — every action that's ever
  fired, with the decided-by analyst.

Reject one pending action with a reason like "Internal scanner, not malicious".

> **Say out loud:** "Every action row in the database carries `simulated=TRUE`
> — enforced by a CHECK constraint. There is no code path in the project
> that contacts a real firewall."

---

## Step 6 — Reports on `/reports` (~1 min)

- **Alerts without a report** card on the top-left — one-click "Generate"
  per row.
- **All reports** list below it.
- **Viewer** on the right — full markdown rendering (headings, GFM tables,
  blockquotes, code) with **Copy markdown** and **Download .md** buttons.

Click the report you generated in Step 4. Scroll through the 8 sections:

```
1. Incident Overview      2. Severity & Priority
3. Detection Results      4. Investigation Findings
5. Timeline               6. Response Recommendations
7. Analyst Action Status  8. Final Summary
```

Click **Generate daily summary** in the page header — a `DAILY_SUMMARY`
report appears and auto-selects.

> **Say out loud:** "The report is structured JSON underneath — what you see
> rendered here is also exactly what the backend's `summary` JSONB column
> stores. It can be downloaded as markdown, copy-pasted into Slack, or
> rendered to PDF by `pandoc` in CI."

---

## Step 7 — Wrap up: ethics + audit (~30 s)

In the terminal:

```bash
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  SELECT agent, decision->>'verb' AS verb,
         decision->>'severity' AS severity,
         decision->>'predicted_label' AS label
  FROM agent_decisions
  WHERE alert_id = <ALERT_ID_FROM_STEP_4>
  ORDER BY id;
"
```

You'll see the entire chain `DETECTION → TRIAGE → RESPONSE → ANALYST(…) →
INVESTIGATION → ANALYST(…) → REPORTING`.

Then prove the ethics guardrail:

```bash
docker compose exec postgres psql -U sentinelai -d sentinelai -c "
  INSERT INTO response_actions (alert_id, action_type, simulated)
  VALUES (1, 'BLOCK_IP', FALSE);
"
# → ERROR: new row for relation "response_actions" violates check
#          constraint "ck_response_actions_simulated_only"
```

> **Say out loud:** "Even with raw SQL, the database refuses to record an
> action that says it ran for real."

---

## Automated smoke test

The same end-to-end flow, scripted:

```bash
bash infra/scripts/smoke_demo.sh
```

Output (truncated):

```
SentinelAI smoke test — target: http://localhost:8000

==> 1. Backend health
    ✓ backend is up
    ✓ database is ready
==> 2. Detection model loaded
    ✓ model loaded: sentinelai-detection@v20260523-…
==> 3. Ingest bundled sample CSV
    ✓ ingested job #1: 20 valid / 0 invalid / 20 total
==> 4. Run detection (auto-triage + auto-respond inline)
    ✓ detection processed 20 event(s) · 13 alert(s) created · 7 benign
==> 5. Dashboard overview
    ✓ dashboard: 20 events · 13 alerts · 3 pending actions
==> 6. Pick an alert and investigate
    ✓ picked alert #1
    ✓ investigation generated — 4 related alert(s)
==> 7. Analyst disposition: CONFIRMED
    ✓ alert #1 disposition = CONFIRMED
==> 8. Approve a pending response action (if any)
    ✓ approved response action #5
==> 9. Generate per-alert report
    ✓ report #1: Incident Report — Alert #1 (BruteForce)
==> 10. Generate daily summary
    ✓ daily summary #2 — 13 alert(s) covered
==> 11. Audit trail on alert #1
    ✓ 7 agent_decisions row(s) · 3 response_action row(s)
    · agents in the chain: DETECTION, TRIAGE, RESPONSE, ANALYST, INVESTIGATION, REPORTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Full pipeline executed successfully.
```

The script exits non-zero on the first failed step, with a `✗` line
explaining what went wrong — useful as a CI gate or a pre-demo sanity check.

---

## Reset between demos

```bash
docker compose down -v        # wipes the database volume
docker compose up -d
docker compose exec backend alembic upgrade head
# (model artifacts under ml/artifacts/ survive — no need to re-train)
docker compose restart backend
```
