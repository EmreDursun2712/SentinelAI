"""Flow-log parsers: Zeek ``conn.log`` and Suricata ``eve.json``.

Each parser turns one log line into a backend ``FlowRecordIn``-shaped dict:

    {event_time, src_ip, dst_ip, src_port, dst_port, protocol, label?, features}

Only flow *metadata* is read — never packet payloads. Unknown/irrelevant lines
return ``None``. Features missing from the CIC-IDS2017 model are fine; the
backend's median imputer handles NaN/absent columns.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

# Zeek conn.log sentinels for "unset".
_ZEEK_UNSET = {"-", "(empty)", ""}


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def _int(value: Any) -> int | None:
    f = _num(value)
    return int(f) if f is not None else None


def _rate(total: float | None, duration: float | None) -> float | None:
    if total is None or duration is None or duration <= 0:
        return None
    return round(total / duration, 4)


def _build_features(
    *,
    duration: float | None,
    fwd_packets: int | None,
    bwd_packets: int | None,
    fwd_bytes: float | None,
    bwd_bytes: float | None,
) -> dict[str, Any]:
    packets = None
    if fwd_packets is not None or bwd_packets is not None:
        packets = (fwd_packets or 0) + (bwd_packets or 0)
    total_bytes = None
    if fwd_bytes is not None or bwd_bytes is not None:
        total_bytes = (fwd_bytes or 0) + (bwd_bytes or 0)

    features: dict[str, Any] = {}

    def put(key: str, val: Any) -> None:
        if val is not None:
            features[key] = val

    put("flow_duration", duration)
    put("duration", duration)
    put("total_fwd_packets", fwd_packets)
    put("total_backward_packets", bwd_packets)
    put("total_length_of_fwd_packets", fwd_bytes)
    put("total_length_of_bwd_packets", bwd_bytes)
    put("bytes", total_bytes)
    put("packets", packets)
    put("flow_bytes/s", _rate(total_bytes, duration))
    put("flow_packets/s", _rate(packets, duration))
    return features


# ---------------------------------------------------------------------------
# Zeek conn.log (TSV with #fields header).
# ---------------------------------------------------------------------------


class ZeekConnParser:
    """Stateful Zeek conn.log parser.

    Tracks the column layout from the ``#fields`` header (Zeek emits it once at
    the top of the file), so ``feed`` can be called line-by-line while tailing.
    """

    def __init__(self) -> None:
        self._fields: list[str] | None = None
        self._sep = "\t"

    def feed(self, line: str) -> dict[str, Any] | None:
        if line is None:
            return None
        line = line.rstrip("\n")
        if not line:
            return None
        if line.startswith("#"):
            self._read_directive(line)
            return None
        if self._fields is None:
            return None  # data before a #fields header — can't map columns
        cols = line.split(self._sep)
        if len(cols) != len(self._fields):
            return None
        row = dict(zip(self._fields, cols, strict=False))
        return self._to_flow(row)

    def _read_directive(self, line: str) -> None:
        if line.startswith("#separator"):
            sep = line.split(" ", 1)[1].strip() if " " in line else "\\x09"
            if sep.startswith("\\x"):
                try:
                    self._sep = chr(int(sep[2:], 16))
                except ValueError:
                    self._sep = "\t"
            else:
                self._sep = sep or "\t"
        elif line.startswith("#fields"):
            parts = line.split(self._sep)
            # First token is "#fields"; the rest are column names.
            self._fields = parts[1:] if len(parts) > 1 else line.split()[1:]

    def _to_flow(self, row: dict[str, str]) -> dict[str, Any] | None:
        def val(key: str) -> str | None:
            v = row.get(key)
            return None if v is None or v in _ZEEK_UNSET else v

        src_ip = val("id.orig_h")
        dst_ip = val("id.resp_h")
        ts = _num(val("ts"))
        if not src_ip or not dst_ip or ts is None:
            return None

        fwd_pkts = _int(val("orig_pkts"))
        bwd_pkts = _int(val("resp_pkts"))
        fwd_bytes = _num(val("orig_bytes"))
        bwd_bytes = _num(val("resp_bytes"))
        duration = _num(val("duration"))

        return {
            "event_time": datetime.fromtimestamp(ts, UTC).isoformat(),
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "src_port": _int(val("id.orig_p")),
            "dst_port": _int(val("id.resp_p")),
            "protocol": (val("proto") or None),
            "features": _build_features(
                duration=duration,
                fwd_packets=fwd_pkts,
                bwd_packets=bwd_pkts,
                fwd_bytes=fwd_bytes,
                bwd_bytes=bwd_bytes,
            ),
        }


def parse_zeek_lines(lines: list[str]) -> list[dict[str, Any]]:
    """One-shot helper (tests / replay): parse a whole conn.log."""
    parser = ZeekConnParser()
    out: list[dict[str, Any]] = []
    for line in lines:
        flow = parser.feed(line)
        if flow is not None:
            out.append(flow)
    return out


# ---------------------------------------------------------------------------
# Suricata eve.json (one JSON object per line; event_type flow|netflow).
# ---------------------------------------------------------------------------


def parse_suricata_line(line: str) -> dict[str, Any] | None:
    if not line or not line.strip():
        return None
    try:
        rec = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(rec, dict):
        return None
    event_type = rec.get("event_type")
    if event_type not in ("flow", "netflow"):
        return None

    src_ip = rec.get("src_ip")
    dst_ip = rec.get("dest_ip")
    if not src_ip or not dst_ip:
        return None

    detail = rec.get(event_type, {}) or {}

    if event_type == "flow":
        fwd_pkts = _int(detail.get("pkts_toserver"))
        bwd_pkts = _int(detail.get("pkts_toclient"))
        fwd_bytes = _num(detail.get("bytes_toserver"))
        bwd_bytes = _num(detail.get("bytes_toclient"))
    else:  # netflow — single-direction counters
        fwd_pkts = _int(detail.get("pkts"))
        bwd_pkts = None
        fwd_bytes = _num(detail.get("bytes"))
        bwd_bytes = None

    duration = _num(detail.get("age"))
    if duration is None:
        duration = _suricata_duration(detail.get("start"), detail.get("end"))

    event_time = detail.get("start") or rec.get("timestamp")
    if not event_time:
        return None

    return {
        "event_time": event_time,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": _int(rec.get("src_port")),
        "dst_port": _int(rec.get("dest_port")),
        "protocol": (str(rec["proto"]).lower() if rec.get("proto") else None),
        "features": _build_features(
            duration=duration,
            fwd_packets=fwd_pkts,
            bwd_packets=bwd_pkts,
            fwd_bytes=fwd_bytes,
            bwd_bytes=bwd_bytes,
        ),
    }


def _suricata_duration(start: Any, end: Any) -> float | None:
    if not start or not end:
        return None
    try:
        s = datetime.fromisoformat(str(start))
        e = datetime.fromisoformat(str(end))
    except ValueError:
        return None
    return max((e - s).total_seconds(), 0.0)


# ---------------------------------------------------------------------------
# Parser selection.
# ---------------------------------------------------------------------------


def make_parser(kind: str):
    """Return a ``parse(line) -> dict | None`` callable for the given kind."""
    if kind == "zeek":
        return ZeekConnParser().feed
    if kind == "suricata":
        return parse_suricata_line
    raise ValueError(f"No parser for kind {kind!r}")


def sniff_kind(first_line: str) -> str:
    """Best-effort format detection for pcap_replay files."""
    stripped = (first_line or "").lstrip()
    if stripped.startswith("{"):
        return "suricata"
    return "zeek"
