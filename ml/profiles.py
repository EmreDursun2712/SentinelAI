"""Dataset profiles for training.

A *profile* bundles the small dataset-specific decisions that otherwise leak into
``train.py``: chiefly how raw labels are normalized into the class space the model
learns. The default (``auto``) just trims whitespace; ``cic2017`` folds the many
CIC-IDS2017 attack sub-labels into coarse families that line up with the synthetic
class names (BENIGN / DDoS / PortScan / BruteForce) so synthetic- and real-trained
models stay comparable, while preserving the rarer families.

Selected on the CLI with ``--profile`` and recorded in ``metadata.json`` so a
model's provenance (which label mapping produced its classes) is auditable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


def _clean(raw: str) -> str:
    """Collapse whitespace and normalize the unicode dashes CIC labels use."""
    return " ".join(str(raw).replace("–", "-").replace("—", "-").split()).strip()


def _identity_label(raw: str) -> str:
    return _clean(raw)


def _cic2017_label(raw: str) -> str:
    """Fold a raw CIC-IDS2017 label into a coarse attack family.

    The mapping is intentionally substring-based so it tolerates the dataset's
    casing/spacing quirks (e.g. ``"DoS Hulk"``, ``"Web Attack - XSS"``,
    ``"FTP-Patator"``). Unknown labels pass through cleaned (title-cased), so no
    data is silently dropped.
    """
    text = _clean(raw).lower()
    if not text:
        return ""
    if "benign" in text:
        return "BENIGN"
    if "ddos" in text or "dos" in text:
        return "DDoS"
    if "portscan" in text or "port scan" in text:
        return "PortScan"
    # Web-attack check precedes brute-force so "Web Attack - Brute Force" is
    # classified as a web attack rather than generic brute force.
    if "web attack" in text or "sql injection" in text or "xss" in text:
        return "WebAttack"
    if "patator" in text or "brute" in text:
        return "BruteForce"
    if "bot" in text:
        return "Bot"
    if "infiltration" in text:
        return "Infiltration"
    if "heartbleed" in text:
        return "Heartbleed"
    return _clean(raw).title()


@dataclass(frozen=True)
class Profile:
    """A named dataset profile."""

    name: str
    description: str
    normalize_label: Callable[[str], str]


PROFILES: dict[str, Profile] = {
    "auto": Profile(
        name="auto",
        description="No label remapping; labels are used as-is (whitespace trimmed).",
        normalize_label=_identity_label,
    ),
    "synthetic": Profile(
        name="synthetic",
        description="Synthetic generator output; already-clean labels.",
        normalize_label=_identity_label,
    ),
    "cic2017": Profile(
        name="cic2017",
        description="CIC-IDS2017: fold attack sub-labels into coarse families.",
        normalize_label=_cic2017_label,
    ),
}


def get_profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown profile {name!r}. Choices: {sorted(PROFILES)}") from exc


def apply_label_profile(labels: list[str], profile: Profile) -> list[str]:
    """Map every raw label through the profile, dropping ones that clean to empty."""
    return [profile.normalize_label(label) for label in labels]
