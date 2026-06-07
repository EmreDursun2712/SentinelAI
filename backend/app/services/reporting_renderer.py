"""Pure-Python markdown renderers for incident reports.

Kept in its own module so the renderers are unit-testable without touching
the database. Every cell is escaped through ``_md_cell`` so pipes / newlines
inside payload values can't break a table.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.schemas.reporting import (
    AlertReportPacket,
    AnalystSection,
    DailySummaryPacket,
    DetectionSection,
    InvestigationSection,
    OverviewSection,
    ResponseSection,
    SeverityPrioritySection,
    TimelineSection,
)

# ---------- helpers --------------------------------------------------------


def _md_cell(value: Any) -> str:
    """Escape a value so it fits in one markdown table cell."""
    if value is None:
        return "—"
    s = str(value).replace("\r", " ").replace("\n", " ")
    return s.replace("|", "\\|").strip() or "—"


def _md_dt(value: Any) -> str:
    if value is None:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return _md_cell(value)


def _md_float(value: float | int | None, *, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _join_table(header: list[str], rows: Iterable[list[Any]]) -> list[str]:
    out: list[str] = []
    out.append("| " + " | ".join(_md_cell(h) for h in header) + " |")
    align = ["---"] * len(header)
    out.append("|" + "|".join(align) + "|")
    for row in rows:
        out.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return out


# ---------- per-alert renderer --------------------------------------------


def render_alert_report_markdown(packet: AlertReportPacket) -> str:
    """Render an ``AlertReportPacket`` as professional markdown."""
    lines: list[str] = []

    lines.append(f"# {packet.title}")
    lines.append("")
    lines.append(
        f"> **Generated (UTC):** {_md_dt(packet.generated_at)}  "
        f"**·** **Status:** `{packet.workflow_status.value}`  "
        f"**·** **Disposition:** `{packet.disposition.value}`"
    )
    lines.append("")

    lines.extend(_render_overview(packet.overview))
    lines.append("")
    lines.extend(_render_severity_priority(packet.severity_priority))
    lines.append("")
    lines.extend(_render_detection(packet.detection))
    lines.append("")
    lines.extend(_render_investigation(packet.investigation))
    lines.append("")
    lines.extend(_render_timeline(packet.timeline))
    lines.append("")
    lines.extend(_render_response(packet.response))
    lines.append("")
    lines.extend(_render_analyst(packet.analyst))
    lines.append("")
    lines.extend(_render_final(packet.final_summary))
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_overview(o: OverviewSection) -> list[str]:
    lines = ["## 1. Incident Overview", ""]
    src = f"{o.src_ip}:{o.src_port}" if o.src_port is not None else o.src_ip
    dst = f"{o.dst_ip}:{o.dst_port}" if o.dst_port is not None else o.dst_ip
    proto = f" ({o.protocol})" if o.protocol else ""
    model = f"{o.model_name}@{o.model_version}" if o.model_name else "— (no model attached)"
    rows = [
        ["**Alert ID**", f"#{o.alert_id}"],
        ["**Created (UTC)**", _md_dt(o.created_at)],
        ["**Source**", src],
        ["**Destination**", dst + proto],
        ["**Predicted family**", o.prediction or "—"],
        ["**Model**", model],
    ]
    lines.extend(_join_table(["Field", "Value"], rows))
    return lines


def _render_severity_priority(s: SeverityPrioritySection) -> list[str]:
    lines = ["## 2. Severity & Priority", ""]
    sev = s.severity.value if s.severity is not None else "unrated"
    rows = [
        ["**Severity**", sev],
        ["**Priority**", _md_float(s.priority, digits=1)],
        ["**Triaged at (UTC)**", _md_dt(s.triaged_at)],
    ]
    lines.extend(_join_table(["Field", "Value"], rows))
    lines.append("")

    if s.explanations:
        lines.append("**Triage factors:**")
        lines.append("")
        for ex in s.explanations:
            lines.append(f"- {ex}")
    elif s.factors:
        f = s.factors
        lines.append("**Triage factors:**")
        lines.append("")
        if f.family_score is not None:
            lines.append(f"- family={f.family or '—'} → score {f.family_score:.2f}")
        if f.confidence_score is not None:
            lines.append(f"- confidence → score {f.confidence_score:.2f}")
        if f.port_score is not None:
            lines.append(
                f"- dst_port={f.dst_port if f.dst_port is not None else '—'} → score {f.port_score:.2f}"
            )
        if f.volume_score is not None:
            lines.append(f"- volume → score {f.volume_score:.2f}")
    else:
        lines.append("_No triage factors recorded — alert may not have been triaged yet._")
    return lines


def _render_detection(d: DetectionSection | None) -> list[str]:
    lines = ["## 3. Detection Results", ""]
    if d is None:
        lines.append("_No detection decision recorded for this alert._")
        return lines

    model = f"{d.model_name}@{d.model_version}" if d.model_name else "—"
    rows = [
        ["**Predicted label**", d.predicted_label],
        ["**Confidence**", _md_float(d.confidence, digits=4)],
        ["**Threshold**", _md_float(d.threshold, digits=2)],
        ["**Model**", model],
    ]
    lines.extend(_join_table(["Field", "Value"], rows))

    if d.class_probabilities:
        lines.append("")
        lines.append("**Class probabilities:**")
        lines.append("")
        sorted_probs = sorted(d.class_probabilities.items(), key=lambda kv: kv[1], reverse=True)
        lines.extend(
            _join_table(
                ["Class", "Probability"],
                [[k, _md_float(v, digits=4)] for k, v in sorted_probs],
            )
        )
    return lines


def _render_investigation(inv: InvestigationSection) -> list[str]:
    lines = ["## 4. Investigation Findings", ""]
    if not inv.available:
        lines.append(
            "_No investigation packet available. Run `POST /api/v1/alerts/{id}/investigate` "
            "before generating a report to include findings here._"
        )
        return lines

    if inv.summary:
        lines.append(f"> {inv.summary}")
        lines.append("")

    if inv.bullets:
        for b in inv.bullets:
            lines.append(f"- {b}")
        lines.append("")

    stats = inv.statistics or {}
    if stats:
        keep = [
            "related_event_count",
            "related_alert_count",
            "same_src_ip_alert_count",
            "same_dst_ip_alert_count",
            "same_family_alert_count",
            "distinct_source_ips",
            "distinct_destination_ips",
            "activity_span_seconds",
            "top_label",
            "top_prediction",
        ]
        rows = [[k, stats.get(k, "—")] for k in keep if k in stats]
        if rows:
            lines.append("**Statistics:**")
            lines.append("")
            lines.extend(_join_table(["Metric", "Value"], rows))

    if inv.feature_importance:
        lines.append("")
        lines.append("**Top contributing features (global model importance):**")
        lines.append("")
        lines.extend(
            _join_table(
                ["Feature", "Importance"],
                [
                    [fi.feature, _md_float(fi.importance, digits=4)]
                    for fi in inv.feature_importance[:10]
                ],
            )
        )

    if inv.generated_at:
        lines.append("")
        lines.append(f"_Packet generated {_md_dt(inv.generated_at)} UTC._")
    return lines


def _render_timeline(t: TimelineSection) -> list[str]:
    lines = ["## 5. Timeline", ""]
    if not t.items:
        lines.append("_No timeline data available._")
        return lines

    rows: list[list[Any]] = []
    for item in t.items:
        marker = "▶ **THIS ALERT** " if item.is_current_alert else ""
        rows.append(
            [
                _md_dt(item.timestamp),
                item.kind,
                marker + item.summary,
            ]
        )
    lines.extend(_join_table(["Time (UTC)", "Kind", "Summary"], rows))
    return lines


def _render_response(r: ResponseSection) -> list[str]:
    lines = ["## 6. Response Recommendations", ""]
    if not r.actions:
        lines.append("_No response actions recorded for this alert._")
        return lines

    rows: list[list[Any]] = []
    for a in r.actions:
        approval = "analyst" if a.approval_required else "auto"
        rationale = a.rationale or "—"
        rows.append(
            [
                a.id,
                a.action_type.value,
                approval,
                a.status.value,
                "yes" if a.executed else "no",
                rationale,
            ]
        )
    lines.extend(_join_table(["#", "Action", "Approval", "Status", "Executed", "Rationale"], rows))

    lines.append("")
    lines.append(
        f"_Totals: {r.auto_executed} auto-executed, "
        f"{r.awaiting_approval} awaiting approval, {r.rejected} rejected._"
    )
    return lines


def _render_analyst(a: AnalystSection) -> list[str]:
    lines = ["## 7. Analyst Action Status", ""]
    rows = [
        ["**Workflow status**", a.status.value],
        ["**Disposition**", a.disposition.value],
    ]
    lines.extend(_join_table(["Field", "Value"], rows))

    lines.append("")
    if not a.entries:
        lines.append("_No analyst actions recorded yet._")
        return lines

    lines.append("**Analyst activity:**")
    lines.append("")
    for entry in a.entries:
        ts = _md_dt(entry.timestamp)
        analyst = entry.analyst_id or "anonymous"
        lines.append(f"- `{ts}` — **{analyst}** — {entry.detail}")
    return lines


def _render_final(summary: str) -> list[str]:
    return ["## 8. Final Summary", "", summary or "_No summary._"]


# ---------- daily-summary renderer ----------------------------------------


def render_daily_summary_markdown(packet: DailySummaryPacket) -> str:
    lines: list[str] = []
    lines.append(f"# {packet.title}")
    lines.append("")
    lines.append(
        f"> **Generated (UTC):** {_md_dt(packet.generated_at)}  "
        f"**·** **Period:** {_md_dt(packet.period_start)} → {_md_dt(packet.period_end)}"
    )
    lines.append("")

    lines.append("## Totals")
    lines.append("")
    lines.append(f"- **Alerts created:** {packet.total_alerts}")
    lines.append(f"- **Response actions created:** {packet.response_actions_total}")
    lines.append("")

    def _stat_table(title: str, mapping: dict[str, int]) -> None:
        lines.append(f"### {title}")
        lines.append("")
        if not mapping:
            lines.append("_No data in this period._")
            return
        rows = sorted(mapping.items(), key=lambda kv: -kv[1])
        lines.extend(_join_table(["Bucket", "Count"], [[k, v] for k, v in rows]))

    _stat_table("By severity", packet.by_severity)
    lines.append("")
    _stat_table("By status", packet.by_status)
    lines.append("")
    _stat_table("By disposition", packet.by_disposition)
    lines.append("")
    _stat_table("Response actions by type", packet.response_actions_by_type)
    lines.append("")
    _stat_table("Response actions by status", packet.response_actions_by_status)
    lines.append("")

    def _top_table(title: str, rows: list[dict[str, Any]], key_label: str) -> None:
        lines.append(f"### {title}")
        lines.append("")
        if not rows:
            lines.append("_No data in this period._")
            return
        body = [[r.get(key_label.lower().replace(" ", "_"), "—"), r.get("count", 0)] for r in rows]
        lines.extend(_join_table([key_label, "Count"], body))

    _top_table("Top source IPs", packet.top_sources, "Source IP")
    lines.append("")
    _top_table("Top destination IPs", packet.top_destinations, "Destination IP")
    lines.append("")
    _top_table("Top predictions", packet.top_predictions, "Prediction")
    lines.append("")

    lines.append("## Mean latencies (seconds)")
    lines.append("")
    rows = [
        ["**Detection → Triage**", _md_float(packet.mean_triage_latency_seconds, digits=2)],
        ["**Detection → Response**", _md_float(packet.mean_response_latency_seconds, digits=2)],
        [
            "**Detection → Investigation**",
            _md_float(packet.mean_investigation_latency_seconds, digits=2),
        ],
        ["**Detection → Report**", _md_float(packet.mean_report_latency_seconds, digits=2)],
    ]
    lines.extend(_join_table(["Stage", "Mean (s)"], rows))
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(packet.final_summary or "_No summary._")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
