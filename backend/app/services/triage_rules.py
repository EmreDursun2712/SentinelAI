"""Explainable triage rules.

Each component contributes a normalized score in ``[0, 1]`` that is mixed by a
fixed weight to produce the final priority (``0–100``). Severity is then a
deterministic mapping from priority. The mixing happens entirely in Python so
the whole derivation is auditable — every alert can show *why* it landed where
it did.

The four components and their mixing weights:

    family      40%  — attack family (DDoS / BruteForce / Infiltration / …)
    confidence  30%  — the model's top-class probability
    port        20%  — destination port sensitivity (SSH/RDP/DB > HTTP > DNS)
    volume      10%  — alerts from the same src_ip in the recent window

These weights are constants below; the service layer is allowed to override
``recent_count`` (the only externally-derived input) but never the weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


# ----- Component lookup tables --------------------------------------------


# Attack-family criticality. The substring fallback in ``family_weight`` lets
# us match values like ``"Web Attack – XSS"`` or ``"DoS Hulk"`` produced by
# CIC-IDS2017 without enumerating every variant.
FAMILY_WEIGHTS: Final[dict[str, float]] = {
    "BENIGN": 0.00,
    "PortScan": 0.55,
    "BruteForce": 0.70,
    "WebAttack": 0.85,
    "SqlInjection": 0.90,
    "DDoS": 0.85,
    "DoS": 0.80,
    "Botnet": 0.95,
    "Bot": 0.95,
    "Infiltration": 1.00,
    "Heartbleed": 1.00,
}
DEFAULT_FAMILY_WEIGHT: Final[float] = 0.50


# Destination-port sensitivity. Numbers chosen to reflect typical SOC weighting:
# admin/auth/database ports score higher than generic HTTP/DNS.
PORT_CRITICALITY: Final[dict[int, float]] = {
    22: 0.85,    # SSH
    23: 0.95,    # Telnet
    25: 0.55,    # SMTP
    53: 0.40,    # DNS
    80: 0.45,    # HTTP
    110: 0.50,   # POP3
    143: 0.55,   # IMAP
    443: 0.50,   # HTTPS
    445: 0.85,   # SMB
    993: 0.55,   # IMAPS
    1433: 0.85,  # MSSQL
    1521: 0.80,  # Oracle
    3306: 0.80,  # MySQL
    3389: 0.90,  # RDP
    5432: 0.80,  # PostgreSQL
    6379: 0.75,  # Redis
    8080: 0.45,  # HTTP-alt
    9200: 0.70,  # Elasticsearch
    27017: 0.75, # MongoDB
}
DEFAULT_PORT_WEIGHT: Final[float] = 0.30


# Volume buckets — escalate when the same src_ip is producing many alerts.
# Tuples of (lower_bound, score). The highest threshold below ``recent_count``
# wins; ties keep the higher score.
VOLUME_BUCKETS: Final[tuple[tuple[int, float], ...]] = (
    (0, 0.00),
    (1, 0.10),
    (5, 0.30),
    (20, 0.55),
    (50, 0.80),
    (200, 1.00),
)


# Final mixing weights. Must sum to 1.0.
COMPONENT_WEIGHTS: Final[dict[str, float]] = {
    "family": 0.40,
    "confidence": 0.30,
    "port": 0.20,
    "volume": 0.10,
}


# Severity tiers — fixed cutoffs on the priority score so dashboards can label
# without re-running the rule engine.
SEVERITY_TIERS: Final[tuple[tuple[float, str], ...]] = (
    (85.0, "CRITICAL"),
    (60.0, "HIGH"),
    (30.0, "MEDIUM"),
    (0.0, "LOW"),
)


# ----- Per-component helpers ----------------------------------------------


def family_weight(family: str | None) -> float:
    """Look up the family's weight, tolerating dataset-specific spellings."""
    if not family:
        return DEFAULT_FAMILY_WEIGHT
    if family in FAMILY_WEIGHTS:
        return FAMILY_WEIGHTS[family]
    cleaned = family.lower().replace(" ", "").replace("-", "").replace("_", "")
    for key, w in FAMILY_WEIGHTS.items():
        if key.lower() in cleaned:
            return w
    return DEFAULT_FAMILY_WEIGHT


def port_criticality(port: int | None) -> float:
    if port is None:
        return DEFAULT_PORT_WEIGHT
    return PORT_CRITICALITY.get(int(port), DEFAULT_PORT_WEIGHT)


def volume_score(recent_count: int) -> float:
    score = 0.0
    for threshold, weight in VOLUME_BUCKETS:
        if recent_count >= threshold:
            score = weight
    return score


def severity_from_priority(priority: float) -> str:
    for threshold, label in SEVERITY_TIERS:
        if priority >= threshold:
            return label
    return "LOW"


# ----- Combined score -----------------------------------------------------


@dataclass(frozen=True)
class TriageScore:
    """Full audit trail of a triage decision."""

    family: str | None
    family_score: float
    confidence_score: float
    dst_port: int | None
    port_score: float
    recent_count: int
    volume_score: float
    component_weights: dict[str, float]
    priority: float          # 0–100, rounded to two decimals
    severity: str            # LOW / MEDIUM / HIGH / CRITICAL
    explanations: list[str]  # human-readable rationale, one line per factor


def compute_score(
    *,
    family: str | None,
    confidence: float,
    dst_port: int | None,
    recent_count: int,
) -> TriageScore:
    """Run the rule engine. ``recent_count`` is the only DB-derived input."""
    fw = family_weight(family)
    pw = port_criticality(dst_port)
    vw = volume_score(recent_count)
    conf = max(0.0, min(1.0, confidence))

    priority_0_1 = (
        COMPONENT_WEIGHTS["family"] * fw
        + COMPONENT_WEIGHTS["confidence"] * conf
        + COMPONENT_WEIGHTS["port"] * pw
        + COMPONENT_WEIGHTS["volume"] * vw
    )
    priority = round(priority_0_1 * 100.0, 2)

    return TriageScore(
        family=family,
        family_score=fw,
        confidence_score=conf,
        dst_port=dst_port,
        port_score=pw,
        recent_count=recent_count,
        volume_score=vw,
        component_weights=dict(COMPONENT_WEIGHTS),
        priority=priority,
        severity=severity_from_priority(priority),
        explanations=[
            f"family={family or 'UNKNOWN'} → criticality {fw:.2f} × 40%",
            f"confidence={conf:.2f} → confidence {conf:.2f} × 30%",
            f"dst_port={dst_port if dst_port is not None else '∅'} → criticality {pw:.2f} × 20%",
            f"recent_src_ip_alerts={recent_count} → volume {vw:.2f} × 10%",
            f"priority={priority:.2f} → severity={severity_from_priority(priority)}",
        ],
    )
