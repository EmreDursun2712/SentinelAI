"""Feature handling shared between training and backend inference.

Keeps the column-normalization logic aligned with
``backend/app/ingestion/feature_schema.py`` so a model trained here is
consumable by the backend at inference time.
"""

from __future__ import annotations

from typing import Final


# Columns that should never be treated as features. Anything else that is
# numeric after normalization is fair game.
EXCLUDED_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "event_time",
        "timestamp",
        "time",
        "src_ip",
        "dst_ip",
        "source_ip",
        "destination_ip",
        "src_port",
        "dst_port",
        "source_port",
        "destination_port",
        "protocol",
        "proto",
        "label",
        "class",
        "flow_id",
        "fwd_header_length.1",  # CIC-IDS2017 duplicate column quirk
    }
)


def normalize_column(name: str | None) -> str:
    """Lower-case, strip, collapse whitespace, replace spaces with underscore.

    Mirrors ``backend/app/ingestion/feature_schema.py:normalize_column``.
    """
    if not name:
        return ""
    cleaned = " ".join(str(name).strip().lower().split())
    return cleaned.replace(" ", "_")


def is_feature_column(name: str) -> bool:
    return normalize_column(name) not in EXCLUDED_COLUMNS
