"""Row-level parsing of normalized CSV input → ``ParsedFlow``.

A clean separation: this module knows *nothing* about CSV files. It takes a dict
keyed by raw CSV headers and returns a fully validated ``ParsedFlow`` (or raises
``ValueError`` / ``pydantic.ValidationError``). The streaming layer above turns
those errors into per-row failures.
"""

from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any, Final

from pydantic import BaseModel, Field, field_validator

from app.ingestion.feature_schema import (
    coerce_feature_value,
    normalize_column,
    normalize_protocol,
    to_int_or_none,
)


# Keys lifted onto the ``NetworkEvent`` row itself, in priority of the data model.
PRIMARY_KEYS: Final[frozenset[str]] = frozenset(
    {"event_time", "src_ip", "dst_ip", "src_port", "dst_port", "protocol", "label"}
)


_TIME_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %I:%M:%S %p",
    "%d/%m/%Y %I:%M %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
)


def parse_event_time(raw: str) -> datetime:
    """Parse ISO 8601 first; fall back to a handful of CIC-IDS2017-style formats."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("event_time is empty")

    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = None
        for fmt in _TIME_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            raise ValueError(f"unrecognized event_time format: {raw!r}") from None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class ParsedFlow(BaseModel):
    """Validated representation of one ingestion row."""

    event_time: datetime
    src_ip: str
    dst_ip: str
    src_port: int | None = None
    dst_port: int | None = None
    protocol: str | None = None
    label: str | None = None
    features: dict[str, Any] = Field(default_factory=dict)

    @field_validator("src_ip", "dst_ip")
    @classmethod
    def _validate_ip(cls, v: str) -> str:
        if not v:
            raise ValueError("ip address is required")
        ip_address(v)  # raises ValueError on invalid input
        return v

    @field_validator("src_port", "dst_port")
    @classmethod
    def _validate_port_range(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not (0 <= v <= 65535):
            raise ValueError(f"port out of range: {v}")
        return v


def parse_row(raw_row: dict[str, str | None]) -> ParsedFlow:
    """Normalize one CSV row dict into a ``ParsedFlow``.

    Primary fields are extracted and validated; every other column is dropped
    into the ``features`` dict for downstream ML inference.
    """
    primary: dict[str, str] = {}
    features: dict[str, Any] = {}

    for key, value in raw_row.items():
        norm = normalize_column(key)
        if not norm:
            continue
        if norm in PRIMARY_KEYS:
            primary[norm] = (value or "").strip()
        else:
            coerced = coerce_feature_value(value)
            if coerced is not None:
                features[norm] = coerced

    if "event_time" not in primary or not primary["event_time"]:
        raise ValueError("event_time is required")

    label = primary.get("label", "").strip()
    return ParsedFlow(
        event_time=parse_event_time(primary["event_time"]),
        src_ip=primary.get("src_ip", ""),
        dst_ip=primary.get("dst_ip", ""),
        src_port=to_int_or_none(primary.get("src_port")),
        dst_port=to_int_or_none(primary.get("dst_port")),
        protocol=normalize_protocol(primary.get("protocol")),
        label=label or None,
        features=features,
    )
