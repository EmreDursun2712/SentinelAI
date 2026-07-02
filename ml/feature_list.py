"""Feature handling shared between training and backend inference.

Keeps the column-normalization logic aligned with
``backend/app/ingestion/feature_schema.py`` so a model trained here is
consumable by the backend at inference time.
"""

from __future__ import annotations

from typing import Final


# The canonical 21-feature schema the backend, the bundled demo CSV, and the
# synthetic generator all agree on. Training with ``--feature-set canonical``
# restricts the model to exactly these columns (in this order) so a model
# trained on *real* CIC-IDS2017 data has the same ``feature_order`` as the demo
# expects — i.e. the real model loads and serves the shipped ``sample_flows.csv``
# with 100% feature coverage. ``ml/synthetic.FEATURES`` re-exports this so the
# generator and the canonical schema can never drift apart.
CANONICAL_FEATURES: Final[tuple[str, ...]] = (
    "flow_duration",
    "total_fwd_packets",
    "total_backward_packets",
    "total_length_of_fwd_packets",
    "total_length_of_bwd_packets",
    "fwd_packet_length_mean",
    "bwd_packet_length_mean",
    "flow_bytes/s",
    "flow_packets/s",
    "flow_iat_mean",
    "flow_iat_std",
    "fwd_iat_mean",
    "bwd_iat_mean",
    "packet_length_mean",
    "packet_length_std",
    "fin_flag_count",
    "syn_flag_count",
    "rst_flag_count",
    "psh_flag_count",
    "ack_flag_count",
    "average_packet_size",
)


# Some cleaned CIC-IDS2017 mirrors (e.g. Kaggle's ``dhoogla/cicids2017``) rename a
# handful of columns. Map those *normalized* variants back to the canonical key
# so canonical-feature training finds every column regardless of the mirror.
# Applied only when the canonical target isn't already present, so a file that
# already uses the canonical name is never clobbered.
COLUMN_ALIASES: Final[dict[str, str]] = {
    "fwd_packets_length_total": "total_length_of_fwd_packets",
    "bwd_packets_length_total": "total_length_of_bwd_packets",
    "avg_packet_size": "average_packet_size",
}


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


def apply_column_aliases(columns: list[str]) -> list[str]:
    """Rewrite already-normalized column names through :data:`COLUMN_ALIASES`.

    An alias only fires when its canonical target is not already present in
    ``columns``, so a frame that already carries the canonical name is left
    untouched (no accidental duplicate columns).
    """
    present = set(columns)
    out: list[str] = []
    for col in columns:
        target = COLUMN_ALIASES.get(col)
        out.append(target if target is not None and target not in present else col)
    return out
