"""Incident-report PDF rendering (markdown → reportlab)."""

from __future__ import annotations

from app.services.pdf_renderer import render_report_pdf
from app.services.reporting_service import render_report_pdf_bytes

SAMPLE_MD = """# Incident Report — Alert #42 (DDoS)

Generated 2026-07-01 · `sentinelai@v1`

## 1. Incident Overview

| Field | Value |
|---|---|
| **Alert ID** | #42 |
| **Prediction** | DDoS |

## 2. Detection

Classified as **DDoS** with 0.98 confidence. Top driver: `flow_duration`.

- BENIGN → 0.01
- DDoS → 0.98

> Investigation found 3 related alerts.

---

_No triage factors recorded._
"""


def test_renders_valid_pdf_bytes() -> None:
    pdf = render_report_pdf(SAMPLE_MD, title="Alert #42")
    assert pdf.startswith(b"%PDF"), "output is not a PDF"
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 1000  # a real multi-flowable document, not an empty shell


def test_empty_markdown_does_not_crash() -> None:
    pdf = render_report_pdf("", title="Empty")
    assert pdf.startswith(b"%PDF")


def test_feature_names_with_underscores_are_not_italicized() -> None:
    # A regression guard: ``flow_duration`` must not trip the _italic_ rule.
    pdf = render_report_pdf("Top feature: flow_duration and total_fwd_packets.", title="x")
    assert pdf.startswith(b"%PDF")


def test_service_helper_returns_bytes() -> None:
    out = render_report_pdf_bytes(SAMPLE_MD, "Alert #42")
    assert out is not None
    assert out.startswith(b"%PDF")
