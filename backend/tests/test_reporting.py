"""Reporting renderer + section-builder tests. No DB required."""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_t
from types import SimpleNamespace

from app.models.enums import (
    AgentName,
    AlertDisposition,
    AlertStatus,
    IncidentKind,
    ResponseActionType,
    ResponseStatus,
    Severity,
)
from app.schemas.reporting import (
    AlertReportPacket,
    AnalystEntry,
    AnalystSection,
    DailySummaryPacket,
    DetectionSection,
    FeatureImportanceItem,
    InvestigationSection,
    OverviewSection,
    ResponseActionRow,
    ResponseSection,
    SeverityPrioritySection,
    TimelineRow,
    TimelineSection,
    TriageFactors,
)
from app.services.reporting_renderer import (
    _md_cell,
    render_alert_report_markdown,
    render_daily_summary_markdown,
)
from app.services.reporting_service import (
    _build_analyst_section,
    _build_detection,
    _build_final_summary,
    _build_investigation,
    _build_overview,
    _build_response_section,
    _build_severity_priority,
    _build_timeline,
    _format_analyst_summary,
)

T0 = datetime(2026, 5, 21, 8, 25, 42, tzinfo=UTC)


# ---------- _md_cell ------------------------------------------------------


def test_md_cell_escapes_pipes_and_newlines() -> None:
    assert _md_cell("a|b") == "a\\|b"
    assert _md_cell("first\nsecond") == "first second"
    assert _md_cell(None) == "—"
    assert _md_cell("") == "—"


# ---------- helpers --------------------------------------------------------


def _alert(**ov):
    base = dict(
        id=42,
        src_ip="203.0.113.7",
        dst_ip="10.0.0.10",
        src_port=38821,
        dst_port=22,
        protocol="TCP",
        prediction="BruteForce",
        confidence=0.92,
        severity=Severity.HIGH,
        priority=67.0,
        status=AlertStatus.INVESTIGATED,
        disposition=AlertDisposition.UNDER_REVIEW,
        model_version_id=1,
        created_at=T0,
        triaged_at=datetime(2026, 5, 21, 8, 25, 43, tzinfo=UTC),
        responded_at=datetime(2026, 5, 21, 8, 25, 44, tzinfo=UTC),
        investigated_at=datetime(2026, 5, 21, 8, 30, 0, tzinfo=UTC),
        reported_at=None,
        closed_at=None,
    )
    base.update(ov)
    return SimpleNamespace(**base)


def _detection_decision():
    return SimpleNamespace(
        id=1,
        agent=AgentName.DETECTION,
        decision={"predicted_label": "BruteForce", "confidence": 0.92},
        reasoning={
            "class_probabilities": {"BruteForce": 0.92, "BENIGN": 0.05, "PortScan": 0.03},
            "model_name": "sentinelai-detection",
            "model_version": "v20260521-073940",
            "threshold": 0.5,
            "benign_label": "BENIGN",
        },
        created_at=T0,
    )


def _triage_decision():
    return SimpleNamespace(
        id=2,
        agent=AgentName.TRIAGE,
        decision={"severity": "HIGH", "priority": 67.0, "recent_count": 3},
        reasoning={
            "factors": {
                "family": "BruteForce",
                "family_score": 0.70,
                "confidence_score": 0.92,
                "dst_port": 22,
                "port_score": 0.85,
                "volume_score": 0.10,
            },
            "component_weights": {"family": 0.40, "confidence": 0.30, "port": 0.20, "volume": 0.10},
            "explanations": ["family=BruteForce → criticality 0.70 × 40%"],
            "window_minutes": 15,
        },
        created_at=datetime(2026, 5, 21, 8, 25, 43, tzinfo=UTC),
    )


def _response_decision():
    return SimpleNamespace(
        id=3,
        agent=AgentName.RESPONSE,
        decision={
            "n_recommendations": 3,
            "n_auto_executed": 3,
            "n_awaiting_approval": 0,
            "action_ids": [10, 11, 12],
        },
        reasoning={"recommendations": []},
        created_at=datetime(2026, 5, 21, 8, 25, 44, tzinfo=UTC),
    )


def _analyst_decision(**ov):
    base = dict(
        id=4,
        agent=AgentName.ANALYST,
        decision={"verb": "approve", "action_id": 10, "action_type": "BLOCK_IP"},
        reasoning={"analyst_id": "alice", "note": "Confirmed: brute-force pattern"},
        created_at=datetime(2026, 5, 21, 9, 5, 0, tzinfo=UTC),
    )
    base.update(ov)
    return SimpleNamespace(**base)


def _action(
    action_id,
    action_type,
    *,
    approval_required=False,
    executed=True,
    stat=ResponseStatus.EXECUTED,
    rationale="test rationale",
):
    return SimpleNamespace(
        id=action_id,
        alert_id=42,
        action_type=action_type,
        simulated=True,
        status=stat,
        executed=executed,
        approval_required=approval_required,
        approved_by=None,
        rejection_reason=None,
        payload={"rationale": rationale, "target_ip": "203.0.113.7"},
        executed_at=datetime(2026, 5, 21, 8, 25, 44, tzinfo=UTC) if executed else None,
        created_at=datetime(2026, 5, 21, 8, 25, 44, tzinfo=UTC),
        updated_at=datetime(2026, 5, 21, 8, 25, 44, tzinfo=UTC),
        decision_id=3,
    )


# ---------- section builders ----------------------------------------------


def test_build_overview_includes_model_when_present() -> None:
    alert = _alert()
    mv = SimpleNamespace(name="sentinelai-detection", version="v1")
    section = _build_overview(alert, mv)
    assert section.alert_id == 42
    assert section.src_ip == "203.0.113.7"
    assert section.dst_port == 22
    assert section.model_name == "sentinelai-detection"


def test_build_overview_handles_no_model() -> None:
    section = _build_overview(_alert(model_version_id=None), None)
    assert section.model_name is None
    assert section.model_version is None


def test_build_severity_priority_extracts_factors_and_explanations() -> None:
    section = _build_severity_priority(_alert(), _triage_decision())
    assert section.severity == Severity.HIGH
    assert section.priority == 67.0
    assert section.factors.family == "BruteForce"
    assert section.factors.port_score == 0.85
    assert section.explanations and "family=BruteForce" in section.explanations[0]
    assert section.component_weights["family"] == 0.40


def test_build_severity_priority_when_not_triaged() -> None:
    alert = _alert(severity=None, priority=None, triaged_at=None)
    section = _build_severity_priority(alert, None)
    assert section.severity is None
    assert section.priority is None
    assert section.explanations == []


def test_build_detection_extracts_class_probabilities() -> None:
    section = _build_detection(_detection_decision())
    assert section is not None
    assert section.predicted_label == "BruteForce"
    assert section.confidence == 0.92
    assert section.threshold == 0.5
    assert section.class_probabilities["BruteForce"] == 0.92


def test_build_detection_returns_none_when_no_decision() -> None:
    assert _build_detection(None) is None


def test_build_investigation_from_packet() -> None:
    packet = {
        "summary": "Investigated alert #42",
        "summary_bullets": ["bullet 1"],
        "statistics": {"related_event_count": 5, "related_alert_count": 3},
        "feature_importance": [{"feature": "flow_bytes/s", "importance": 0.18}],
        "generated_at": T0.isoformat(),
    }
    section = _build_investigation(packet)
    assert section.available is True
    assert section.bullets == ["bullet 1"]
    assert section.statistics["related_event_count"] == 5
    assert section.feature_importance[0].feature == "flow_bytes/s"


def test_build_investigation_returns_unavailable_when_none() -> None:
    section = _build_investigation(None)
    assert section.available is False
    assert section.bullets == []


def test_build_response_section_classifies_actions() -> None:
    actions = [
        _action(10, ResponseActionType.BLOCK_IP),
        _action(11, ResponseActionType.NOTIFY_ANALYST),
        _action(
            12,
            ResponseActionType.SUPPRESS_ALERT,
            approval_required=True,
            executed=False,
            stat=ResponseStatus.PENDING,
        ),
        _action(
            13,
            ResponseActionType.RATE_LIMIT,
            approval_required=True,
            executed=False,
            stat=ResponseStatus.REJECTED,
        ),
    ]
    section = _build_response_section(actions)
    assert section.auto_executed == 2  # BLOCK_IP + NOTIFY_ANALYST
    assert section.awaiting_approval == 1
    assert section.rejected == 1
    assert section.counts_by_status[ResponseStatus.EXECUTED.value] == 2


def test_build_analyst_section_renders_entries() -> None:
    alert = _alert()
    section = _build_analyst_section(alert, [_analyst_decision()])
    assert section.disposition == AlertDisposition.UNDER_REVIEW
    assert len(section.entries) == 1
    e = section.entries[0]
    assert e.analyst_id == "alice"
    assert e.verb == "approve"
    assert "BLOCK_IP" in e.detail


def test_format_analyst_summary_disposition_change() -> None:
    d = SimpleNamespace(
        decision={"disposition_from": "OPEN", "disposition_to": "CONFIRMED"},
        reasoning={"analyst_id": "alice", "note": "real attack"},
    )
    out = _format_analyst_summary(d)
    assert "OPEN" in out and "CONFIRMED" in out
    assert "real attack" in out


def test_format_analyst_summary_approve_with_note() -> None:
    d = SimpleNamespace(
        decision={"verb": "approve", "action_id": 10, "action_type": "BLOCK_IP"},
        reasoning={"analyst_id": "alice", "note": "good call"},
    )
    out = _format_analyst_summary(d)
    assert "APPROVE on BLOCK_IP" in out
    assert "good call" in out


def test_build_timeline_uses_investigation_packet_when_present() -> None:
    packet = {
        "timeline": [
            {
                "timestamp": T0.isoformat(),
                "kind": "event",
                "summary": "Flow",
                "is_current_alert": False,
            },
            {
                "timestamp": (T0).isoformat(),
                "kind": "alert",
                "summary": "This alert",
                "is_current_alert": True,
            },
        ]
    }
    decisions = [_detection_decision(), _triage_decision(), _response_decision()]
    section = _build_timeline(_alert(), packet, decisions, [])
    assert len(section.items) >= 5  # 2 from packet + 3 agent rows
    # current alert flag preserved
    assert any(it.is_current_alert for it in section.items)
    # sorted ascending
    ts = [it.timestamp for it in section.items]
    assert ts == sorted(ts)


def test_build_timeline_synthesizes_when_no_packet() -> None:
    decisions = [_detection_decision()]
    section = _build_timeline(_alert(), None, decisions, [])
    # Synthesized alert row + detection agent row
    assert any(it.is_current_alert for it in section.items)
    assert any("Detection:" in it.summary for it in section.items)


# ---------- final summary --------------------------------------------------


def test_final_summary_combines_all_stages() -> None:
    alert = _alert()
    detection = _build_detection(_detection_decision())
    investigation = _build_investigation(
        {
            "statistics": {"related_alert_count": 5, "same_family_alert_count": 4},
        }
    )
    response = _build_response_section(
        [
            _action(10, ResponseActionType.BLOCK_IP),
            _action(11, ResponseActionType.CREATE_TICKET),
        ]
    )
    text = _build_final_summary(
        alert, detection, _triage_decision(), investigation, response, [_analyst_decision()]
    )
    assert "Alert #42" in text
    assert "BruteForce" in text
    assert "HIGH" in text
    assert "5 related alert(s)" in text
    assert "2 auto-executed" not in text  # we say "auto-executed **2** action(s)"
    assert "auto-executed" in text
    assert "Analyst recorded 1 action(s)" in text
    assert "status `INVESTIGATED`" in text


def test_final_summary_handles_missing_pieces_gracefully() -> None:
    alert = _alert(severity=None, priority=None, triaged_at=None, status=AlertStatus.NEW)
    investigation = _build_investigation(None)
    response = _build_response_section([])
    text = _build_final_summary(alert, None, None, investigation, response, [])
    assert "has no detection-agent record" in text
    assert "No investigation packet attached" in text
    assert "No response actions" in text
    assert "status `NEW`" in text


# ---------- markdown renderer (per-alert) ----------------------------------


def _full_packet() -> AlertReportPacket:
    """Hand-build a fully-populated AlertReportPacket for rendering tests."""
    overview = OverviewSection(
        alert_id=42,
        created_at=T0,
        src_ip="203.0.113.7",
        src_port=38821,
        dst_ip="10.0.0.10",
        dst_port=22,
        protocol="TCP",
        prediction="BruteForce",
        model_name="sentinelai-detection",
        model_version="v20260521-073940",
    )
    severity_priority = SeverityPrioritySection(
        severity=Severity.HIGH,
        priority=67.0,
        factors=TriageFactors(
            family="BruteForce",
            family_score=0.70,
            confidence_score=0.92,
            dst_port=22,
            port_score=0.85,
            volume_score=0.10,
        ),
        component_weights={"family": 0.40, "confidence": 0.30, "port": 0.20, "volume": 0.10},
        explanations=["family=BruteForce → criticality 0.70 × 40%"],
        triaged_at=T0,
    )
    detection = DetectionSection(
        predicted_label="BruteForce",
        confidence=0.92,
        threshold=0.5,
        class_probabilities={"BruteForce": 0.92, "BENIGN": 0.05, "PortScan": 0.03},
        model_name="sentinelai-detection",
        model_version="v20260521-073940",
    )
    investigation = InvestigationSection(
        available=True,
        summary="Investigated alert #42…",
        bullets=["Source 203.0.113.7 has 4 other recent alerts."],
        statistics={"related_event_count": 12, "related_alert_count": 4},
        feature_importance=[FeatureImportanceItem(feature="flow_bytes/s", importance=0.18)],
        generated_at=T0,
    )
    timeline = TimelineSection(
        items=[
            TimelineRow(timestamp=T0, kind="event", summary="Flow"),
            TimelineRow(timestamp=T0, kind="alert", summary="This alert", is_current_alert=True),
        ]
    )
    response = ResponseSection(
        actions=[
            ResponseActionRow(
                id=10,
                action_type=ResponseActionType.BLOCK_IP,
                status=ResponseStatus.EXECUTED,
                approval_required=False,
                executed=True,
                rationale="HIGH BruteForce — auto-block source IP.",
                payload={"target_ip": "203.0.113.7"},
                executed_at=T0,
                created_at=T0,
            )
        ],
        counts_by_status={"EXECUTED": 1},
        auto_executed=1,
        awaiting_approval=0,
        rejected=0,
    )
    analyst = AnalystSection(
        status=AlertStatus.INVESTIGATED,
        disposition=AlertDisposition.UNDER_REVIEW,
        entries=[
            AnalystEntry(
                timestamp=T0,
                analyst_id="alice",
                verb="approve",
                target="BLOCK_IP",
                note="Confirmed",
                detail="APPROVE on BLOCK_IP — “Confirmed”",
            )
        ],
    )
    return AlertReportPacket(
        alert_id=42,
        kind=IncidentKind.PER_ALERT,
        title="Incident Report — Alert #42 (BruteForce)",
        generated_at=T0,
        workflow_status=AlertStatus.INVESTIGATED,
        disposition=AlertDisposition.UNDER_REVIEW,
        overview=overview,
        severity_priority=severity_priority,
        detection=detection,
        investigation=investigation,
        timeline=timeline,
        response=response,
        analyst=analyst,
        final_summary="Alert #42 was a HIGH BruteForce…",
        markdown="",
    )


def test_alert_markdown_contains_all_eight_section_headers() -> None:
    md = render_alert_report_markdown(_full_packet())
    for header in (
        "# Incident Report",
        "## 1. Incident Overview",
        "## 2. Severity & Priority",
        "## 3. Detection Results",
        "## 4. Investigation Findings",
        "## 5. Timeline",
        "## 6. Response Recommendations",
        "## 7. Analyst Action Status",
        "## 8. Final Summary",
    ):
        assert header in md, header


def test_alert_markdown_includes_alert_id_and_predicted_family() -> None:
    md = render_alert_report_markdown(_full_packet())
    assert "#42" in md
    assert "BruteForce" in md
    assert "203.0.113.7" in md
    assert "10.0.0.10:22" in md


def test_alert_markdown_handles_no_investigation() -> None:
    p = _full_packet()
    p.investigation = InvestigationSection(available=False)
    md = render_alert_report_markdown(p)
    assert "## 4. Investigation Findings" in md
    assert "No investigation packet available" in md


def test_alert_markdown_handles_no_detection() -> None:
    p = _full_packet()
    p.detection = None
    md = render_alert_report_markdown(p)
    assert "## 3. Detection Results" in md
    assert "No detection decision recorded" in md


def test_alert_markdown_marks_current_alert_in_timeline() -> None:
    md = render_alert_report_markdown(_full_packet())
    assert "**THIS ALERT**" in md


def test_alert_markdown_is_deterministic() -> None:
    p = _full_packet()
    md1 = render_alert_report_markdown(p)
    md2 = render_alert_report_markdown(p)
    assert md1 == md2


def test_alert_markdown_escapes_pipes_in_rationale() -> None:
    p = _full_packet()
    p.response.actions[0].rationale = "Block | source | now"
    md = render_alert_report_markdown(p)
    # pipes in the cell value should be escaped (avoid breaking the table)
    assert "Block \\| source \\| now" in md


# ---------- markdown renderer (daily summary) ------------------------------


def _full_daily_packet() -> DailySummaryPacket:
    return DailySummaryPacket(
        kind=IncidentKind.DAILY_SUMMARY,
        title="Daily Security Summary — 2026-05-21",
        generated_at=T0,
        date=date_t(2026, 5, 21),
        period_start=datetime(2026, 5, 21, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 22, 0, 0, tzinfo=UTC),
        total_alerts=42,
        by_severity={"CRITICAL": 5, "HIGH": 12, "MEDIUM": 15, "LOW": 10},
        by_status={"TRIAGED": 30, "AUTO_RESPONDED": 8, "CLOSED": 4},
        by_disposition={"OPEN": 30, "CONFIRMED": 8, "FALSE_POSITIVE": 4},
        top_sources=[{"source_ip": "203.0.113.7", "count": 12}],
        top_destinations=[{"destination_ip": "10.0.0.10", "count": 8}],
        top_predictions=[{"prediction": "BruteForce", "count": 18}],
        response_actions_total=120,
        response_actions_by_type={"BLOCK_IP": 25, "NOTIFY_ANALYST": 42},
        response_actions_by_status={"EXECUTED": 90, "PENDING": 25, "REJECTED": 5},
        mean_triage_latency_seconds=0.5,
        mean_response_latency_seconds=1.2,
        mean_investigation_latency_seconds=None,
        mean_report_latency_seconds=None,
        final_summary="42 alerts on 2026-05-21 …",
        markdown="",
    )


def test_daily_markdown_contains_key_sections() -> None:
    md = render_daily_summary_markdown(_full_daily_packet())
    for keyword in (
        "Daily Security Summary",
        "## Totals",
        "### By severity",
        "### By status",
        "### By disposition",
        "### Top source IPs",
        "### Top destination IPs",
        "### Top predictions",
        "Mean latencies",
        "## Summary",
    ):
        assert keyword in md, keyword


def test_daily_markdown_renders_dash_for_missing_latencies() -> None:
    md = render_daily_summary_markdown(_full_daily_packet())
    # mean_investigation_latency_seconds is None — should render as "—"
    assert "Detection → Investigation" in md
    # Find the row and verify it contains "—"
    investigation_row = next(
        line for line in md.splitlines() if "Detection → Investigation" in line
    )
    assert "—" in investigation_row


def test_daily_markdown_handles_zero_data() -> None:
    p = _full_daily_packet()
    p.total_alerts = 0
    p.by_severity = {}
    p.by_status = {}
    p.by_disposition = {}
    p.top_sources = []
    p.top_destinations = []
    p.top_predictions = []
    p.response_actions_total = 0
    p.response_actions_by_type = {}
    p.response_actions_by_status = {}
    md = render_daily_summary_markdown(p)
    assert "No data in this period." in md
