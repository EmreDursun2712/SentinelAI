"""Mapping rules used by the CSV row parser.

Real-world flow datasets (CIC-IDS2017 in particular) are notorious for column-name
quirks: leading whitespace, mixed case, plural/singular differences. This module
normalizes a header into a canonical key, lifts the primary fields out, and lets
everything else fall into the `features` JSONB payload that the Detection Agent
later consumes.
"""

from __future__ import annotations

from typing import Final


# Maps lower-cased, single-space-collapsed CSV headers to canonical keys.
# Anything not present here is normalized to snake_case and dropped into `features`.
COLUMN_ALIASES: Final[dict[str, str]] = {
    "source ip": "src_ip",
    "src ip": "src_ip",
    "src_ip": "src_ip",
    "source_ip": "src_ip",
    "destination ip": "dst_ip",
    "dst ip": "dst_ip",
    "dst_ip": "dst_ip",
    "destination_ip": "dst_ip",
    "source port": "src_port",
    "src port": "src_port",
    "src_port": "src_port",
    "source_port": "src_port",
    "destination port": "dst_port",
    "dst port": "dst_port",
    "dst_port": "dst_port",
    "destination_port": "dst_port",
    "protocol": "protocol",
    "proto": "protocol",
    "timestamp": "event_time",
    "time": "event_time",
    "event_time": "event_time",
    "label": "label",
    "class": "label",
}


# IANA protocol numbers we care about. Strings pass through `.upper()`.
PROTOCOL_NUMBER_TO_NAME: Final[dict[int, str]] = {
    1: "ICMP",
    6: "TCP",
    17: "UDP",
    47: "GRE",
    50: "ESP",
    51: "AH",
    58: "ICMPv6",
}


# Empty / sentinel values that should become None.
_EMPTY_TOKENS: Final[frozenset[str]] = frozenset(
    {"", "nan", "none", "null", "n/a", "na", "inf", "-inf", "infinity", "-infinity"}
)


def normalize_column(name: str | None) -> str:
    """Lower-case, strip, collapse whitespace, apply alias map."""
    if name is None:
        return ""
    cleaned = " ".join(name.strip().lower().split())
    if cleaned in COLUMN_ALIASES:
        return COLUMN_ALIASES[cleaned]
    return cleaned.replace(" ", "_")


def normalize_protocol(value: str | int | None) -> str | None:
    """Accept ``"TCP"``, ``"tcp"``, ``"6"``, or ``6`` and return ``"TCP"``."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _EMPTY_TOKENS:
        return None
    if text.isdigit():
        return PROTOCOL_NUMBER_TO_NAME.get(int(text), text)
    return text.upper()


def coerce_feature_value(raw: str | None) -> float | str | None:
    """Try float; otherwise return the cleaned string; empty / sentinel → ``None``."""
    if raw is None:
        return None
    text = raw.strip()
    if text.lower() in _EMPTY_TOKENS:
        return None
    try:
        return float(text)
    except ValueError:
        return text


def to_int_or_none(raw: str | int | None) -> int | None:
    """Parse a port value, tolerating ``"80.0"`` / empty / NaN inputs."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text.lower() in _EMPTY_TOKENS:
        return None
    try:
        return int(float(text))
    except ValueError as exc:
        raise ValueError(f"invalid integer value: {raw!r}") from exc
