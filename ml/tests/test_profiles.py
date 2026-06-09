"""Dataset-profile label-normalization tests."""

from __future__ import annotations

import pytest

from ml.profiles import apply_label_profile, get_profile


def test_auto_profile_is_identity_but_trims() -> None:
    p = get_profile("auto")
    assert p.normalize_label("  DDoS  ") == "DDoS"
    assert p.normalize_label("BENIGN") == "BENIGN"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BENIGN", "BENIGN"),
        ("DDoS", "DDoS"),
        ("DoS Hulk", "DDoS"),
        ("DoS GoldenEye", "DDoS"),
        ("PortScan", "PortScan"),
        ("Port Scan", "PortScan"),
        ("FTP-Patator", "BruteForce"),
        ("SSH-Patator", "BruteForce"),
        ("Web Attack - Brute Force", "WebAttack"),
        ("Web Attack – XSS", "WebAttack"),
        ("Bot", "Bot"),
        ("Infiltration", "Infiltration"),
        ("Heartbleed", "Heartbleed"),
    ],
)
def test_cic2017_label_mapping(raw: str, expected: str) -> None:
    assert get_profile("cic2017").normalize_label(raw) == expected


def test_apply_label_profile_maps_all() -> None:
    p = get_profile("cic2017")
    out = apply_label_profile(["BENIGN", "DoS Hulk", "FTP-Patator"], p)
    assert out == ["BENIGN", "DDoS", "BruteForce"]


def test_unknown_profile_raises() -> None:
    with pytest.raises(ValueError):
        get_profile("nope")
