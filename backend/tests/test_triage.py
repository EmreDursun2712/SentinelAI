"""Triage rule-engine tests — pure functions, no DB."""

from __future__ import annotations

import pytest

from app.services.triage_rules import (
    COMPONENT_WEIGHTS,
    DEFAULT_FAMILY_WEIGHT,
    DEFAULT_PORT_WEIGHT,
    compute_score,
    family_weight,
    port_criticality,
    severity_from_priority,
    volume_score,
)

# ---------- family_weight --------------------------------------------------


@pytest.mark.parametrize(
    ("family", "expected"),
    [
        ("BENIGN", 0.0),
        ("DDoS", 0.85),
        ("BruteForce", 0.70),
        ("PortScan", 0.55),
        ("Infiltration", 1.00),
        ("Heartbleed", 1.00),
    ],
)
def test_family_weight_exact_match(family: str, expected: float) -> None:
    assert family_weight(family) == pytest.approx(expected)


def test_family_weight_substring_fallback() -> None:
    # CIC-IDS2017 emits values like "Web Attack – XSS" / "DoS Hulk"
    assert family_weight("Web Attack – XSS") == pytest.approx(0.85)
    assert family_weight("DoS Hulk") == pytest.approx(0.80)
    assert family_weight("Bot-net") == pytest.approx(0.95)


def test_family_weight_unknown_returns_default() -> None:
    assert family_weight("Mystery") == pytest.approx(DEFAULT_FAMILY_WEIGHT)
    assert family_weight(None) == pytest.approx(DEFAULT_FAMILY_WEIGHT)
    assert family_weight("") == pytest.approx(DEFAULT_FAMILY_WEIGHT)


# ---------- port_criticality ----------------------------------------------


@pytest.mark.parametrize(
    ("port", "expected"),
    [
        (22, 0.85),  # SSH
        (3389, 0.90),  # RDP
        (3306, 0.80),  # MySQL
        (80, 0.45),  # HTTP
        (443, 0.50),  # HTTPS
        (53, 0.40),  # DNS
    ],
)
def test_port_criticality_known(port: int, expected: float) -> None:
    assert port_criticality(port) == pytest.approx(expected)


def test_port_criticality_unknown_or_null() -> None:
    assert port_criticality(None) == pytest.approx(DEFAULT_PORT_WEIGHT)
    assert port_criticality(54321) == pytest.approx(DEFAULT_PORT_WEIGHT)


# ---------- volume_score (bucketed) ----------------------------------------


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, 0.00),
        (1, 0.10),
        (4, 0.10),
        (5, 0.30),
        (19, 0.30),
        (20, 0.55),
        (49, 0.55),
        (50, 0.80),
        (199, 0.80),
        (200, 1.00),
    ],
)
def test_volume_score_buckets(count: int, expected: float) -> None:
    assert volume_score(count) == pytest.approx(expected)


# ---------- severity_from_priority -----------------------------------------


@pytest.mark.parametrize(
    ("priority", "expected"),
    [
        (0.0, "LOW"),
        (29.99, "LOW"),
        (30.0, "MEDIUM"),
        (59.99, "MEDIUM"),
        (60.0, "HIGH"),
        (84.99, "HIGH"),
        (85.0, "CRITICAL"),
        (100.0, "CRITICAL"),
    ],
)
def test_severity_tier_boundaries(priority: float, expected: str) -> None:
    assert severity_from_priority(priority) == expected


# ---------- compute_score (integration of all components) ------------------


def test_compute_score_high_severity_ddos_on_rdp() -> None:
    # DDoS (0.85) + high confidence (0.92) + RDP (0.90) + busy src_ip (count 30 → 0.55)
    s = compute_score(family="DDoS", confidence=0.92, dst_port=3389, recent_count=30)
    # expected ≈ 0.4*0.85 + 0.3*0.92 + 0.2*0.90 + 0.1*0.55 = 0.34 + 0.276 + 0.18 + 0.055 = 0.851
    assert s.priority == pytest.approx(85.1)
    assert s.severity == "CRITICAL"
    assert s.recent_count == 30


def test_compute_score_medium_severity_brute_force() -> None:
    s = compute_score(family="BruteForce", confidence=0.70, dst_port=22, recent_count=3)
    # expected ≈ 0.4*0.7 + 0.3*0.7 + 0.2*0.85 + 0.1*0.1 = 0.28 + 0.21 + 0.17 + 0.01 = 0.67
    assert s.severity == "HIGH"
    assert s.priority == pytest.approx(67.0)


def test_compute_score_low_severity_unknown_family() -> None:
    # Mystery family (default 0.5), low confidence, obscure port, no volume.
    s = compute_score(family="Mystery", confidence=0.30, dst_port=54321, recent_count=0)
    # expected ≈ 0.4*0.5 + 0.3*0.3 + 0.2*0.3 + 0.1*0.0 = 0.2 + 0.09 + 0.06 + 0 = 0.35
    assert s.severity == "MEDIUM"
    assert s.priority == pytest.approx(35.0)


def test_compute_score_explanations_are_human_readable() -> None:
    s = compute_score(family="DDoS", confidence=0.9, dst_port=22, recent_count=10)
    joined = " ".join(s.explanations)
    assert "family=DDoS" in joined
    assert "dst_port=22" in joined
    assert "recent_src_ip_alerts=10" in joined
    assert "priority=" in joined
    assert "severity=" in joined


def test_compute_score_component_weights_match_module_constants() -> None:
    s = compute_score(family="DDoS", confidence=0.5, dst_port=443, recent_count=0)
    assert s.component_weights == COMPONENT_WEIGHTS


def test_compute_score_confidence_clamped_to_unit_interval() -> None:
    # Out-of-range confidence shouldn't blow priority past 100.
    s_low = compute_score(family="BENIGN", confidence=-0.5, dst_port=80, recent_count=0)
    s_high = compute_score(family="Infiltration", confidence=2.0, dst_port=22, recent_count=200)
    assert 0.0 <= s_low.priority <= 100.0
    assert 0.0 <= s_high.priority <= 100.0
