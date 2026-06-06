"""Parser and CSV-loader tests. No database required."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.ingestion.csv_loader import CsvFormatError, stream_csv
from app.ingestion.feature_schema import (
    coerce_feature_value,
    normalize_column,
    normalize_protocol,
    to_int_or_none,
)
from app.ingestion.parser import parse_event_time, parse_row


# ---------- column normalization ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Source IP", "src_ip"),
        (" source ip ", "src_ip"),
        ("SRC_IP", "src_ip"),
        ("Destination Port", "dst_port"),
        ("Protocol", "protocol"),
        ("Timestamp", "event_time"),
        ("Label", "label"),
        ("Flow Duration", "flow_duration"),
        ("Total Fwd Packets", "total_fwd_packets"),
        ("  ", ""),
        (None, ""),
    ],
)
def test_normalize_column(raw: str | None, expected: str) -> None:
    assert normalize_column(raw) == expected


# ---------- protocol normalization ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TCP", "TCP"),
        ("tcp", "TCP"),
        ("6", "TCP"),
        (6, "TCP"),
        ("17", "UDP"),
        ("1", "ICMP"),
        ("", None),
        (None, None),
        ("NaN", None),
        ("99", "99"),  # unknown number passes through
    ],
)
def test_normalize_protocol(raw: object, expected: str | None) -> None:
    assert normalize_protocol(raw) == expected  # type: ignore[arg-type]


# ---------- feature value coercion ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.5", 1.5),
        ("0", 0.0),
        ("not_a_number", "not_a_number"),
        ("  3.14  ", 3.14),
        ("", None),
        ("NaN", None),
        ("Infinity", None),
        ("inf", None),
        (None, None),
    ],
)
def test_coerce_feature_value(raw: str | None, expected: float | str | None) -> None:
    assert coerce_feature_value(raw) == expected


def test_to_int_or_none_handles_floats_and_sentinels() -> None:
    assert to_int_or_none("80.0") == 80
    assert to_int_or_none("") is None
    assert to_int_or_none("NaN") is None
    assert to_int_or_none(None) is None
    with pytest.raises(ValueError):
        to_int_or_none("abc")


# ---------- event_time parsing ----------


@pytest.mark.parametrize(
    "raw",
    [
        "2024-01-15T08:23:14",
        "2024-01-15 08:23:14",
        "5/7/2017 8:53:00",
        "5/7/2017 8:53",
        "07/05/2017 08:53:00",
    ],
)
def test_parse_event_time_accepts_common_formats(raw: str) -> None:
    parsed = parse_event_time(raw)
    assert parsed.tzinfo is not None  # always timezone-aware


def test_parse_event_time_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_event_time("not-a-date")


# ---------- row parsing ----------


def test_parse_row_extracts_primary_and_features() -> None:
    raw = {
        "Timestamp": "2024-01-15T08:23:14",
        "Source IP": "192.168.1.50",
        "Source Port": "52341",
        "Destination IP": "10.0.0.10",
        "Destination Port": "443",
        "Protocol": "6",
        "Flow Duration": "1450",
        "Total Fwd Packets": "12",
        "Label": "BENIGN",
    }
    flow = parse_row(raw)
    assert flow.src_ip == "192.168.1.50"
    assert flow.dst_ip == "10.0.0.10"
    assert flow.src_port == 52341
    assert flow.dst_port == 443
    assert flow.protocol == "TCP"
    assert flow.label == "BENIGN"
    assert flow.features == {"flow_duration": 1450.0, "total_fwd_packets": 12.0}


def test_parse_row_rejects_invalid_ip() -> None:
    raw = {
        "Timestamp": "2024-01-15T08:23:14",
        "Source IP": "not.an.ip",
        "Destination IP": "10.0.0.10",
    }
    with pytest.raises(Exception):  # pydantic.ValidationError
        parse_row(raw)


def test_parse_row_requires_event_time() -> None:
    raw = {
        "Source IP": "192.168.1.50",
        "Destination IP": "10.0.0.10",
    }
    with pytest.raises(ValueError):
        parse_row(raw)


def test_parse_row_drops_empty_features() -> None:
    raw = {
        "Timestamp": "2024-01-15T08:23:14",
        "Source IP": "192.168.1.50",
        "Destination IP": "10.0.0.10",
        "Flow Duration": "",
        "Some Metric": "NaN",
        "Other": "1.0",
    }
    flow = parse_row(raw)
    assert "flow_duration" not in flow.features
    assert "some_metric" not in flow.features
    assert flow.features == {"other": 1.0}


def test_parse_row_rejects_out_of_range_port() -> None:
    raw = {
        "Timestamp": "2024-01-15T08:23:14",
        "Source IP": "192.168.1.50",
        "Destination IP": "10.0.0.10",
        "Source Port": "70000",
    }
    with pytest.raises(Exception):
        parse_row(raw)


# ---------- streaming loader ----------


def test_stream_csv_yields_results_with_errors() -> None:
    csv_text = (
        "Timestamp,Source IP,Destination IP,Protocol,Label\n"
        "2024-01-15T08:23:14,192.168.1.50,10.0.0.10,TCP,BENIGN\n"
        "2024-01-15T08:23:15,bogus,10.0.0.10,TCP,BENIGN\n"
        ",192.168.1.50,10.0.0.10,TCP,BENIGN\n"
        "2024-01-15T08:23:16,192.168.1.51,10.0.0.11,UDP,BENIGN\n"
    )
    results = list(stream_csv(io.BytesIO(csv_text.encode("utf-8"))))
    assert len(results) == 4
    assert results[0].ok and results[3].ok
    assert not results[1].ok and "ip" in (results[1].error or "").lower()
    assert not results[2].ok and "event_time" in (results[2].error or "").lower()


def test_stream_csv_rejects_empty_file() -> None:
    with pytest.raises(CsvFormatError):
        list(stream_csv(io.BytesIO(b"")))


# ---------- sample CSV golden-path ----------


def test_sample_csv_parses_without_errors() -> None:
    sample = Path(__file__).resolve().parents[1] / "data" / "samples" / "sample_flows.csv"
    with sample.open("rb") as fh:
        results = list(stream_csv(fh))
    assert results, "sample CSV produced no rows"
    assert all(r.ok for r in results), [
        (r.row_number, r.error) for r in results if not r.ok
    ]
