"""Parser tests for Zeek conn.log and Suricata eve.json (stdlib-only)."""

from __future__ import annotations

from pathlib import Path

from sentinelai_sensor.parsers import (
    ZeekConnParser,
    parse_suricata_line,
    parse_zeek_lines,
    sniff_kind,
)

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _read(name: str) -> list[str]:
    return (SAMPLES / name).read_text().splitlines()


# ---------------------------------------------------------------------------
# Zeek.
# ---------------------------------------------------------------------------


def test_zeek_parses_sample_conn_log() -> None:
    flows = parse_zeek_lines(_read("conn.log"))
    assert len(flows) == 3

    first = flows[0]
    assert first["src_ip"] == "192.168.1.10"
    assert first["dst_ip"] == "192.168.1.20"
    assert first["src_port"] == 44321
    assert first["dst_port"] == 443
    assert first["protocol"] == "tcp"
    assert first["event_time"].startswith("2025-")  # epoch → ISO UTC

    f = first["features"]
    assert f["total_fwd_packets"] == 12
    assert f["total_backward_packets"] == 14
    assert f["packets"] == 26
    assert f["bytes"] == 9600  # 1200 + 8400
    assert f["flow_duration"] == 1.5
    assert f["flow_bytes/s"] == 6400.0  # 9600 / 1.5
    assert f["flow_packets/s"] == round(26 / 1.5, 4)


def test_zeek_skips_comments_and_handles_unset() -> None:
    parser = ZeekConnParser()
    # Directives + a #fields header, then one data row with an unset duration.
    for line in [
        "#separator \\x09",
        "#fields\tts\tid.orig_h\tid.orig_p\tid.resp_h\tid.resp_p\tproto\tduration\torig_pkts\tresp_pkts",
        "1700000000.0\t192.168.1.1\t100\t192.168.1.2\t80\ttcp\t-\t5\t6",
    ]:
        flow = parser.feed(line)
    assert flow is not None
    assert flow["protocol"] == "tcp"
    # duration was unset ("-") → no rate features, but packet counts still present
    assert "flow_bytes/s" not in flow["features"]
    assert flow["features"]["total_fwd_packets"] == 5


def test_zeek_ignores_data_before_fields_header() -> None:
    parser = ZeekConnParser()
    assert parser.feed("1700000000.0\t1.2.3.4\t1\t5.6.7.8\t2\ttcp") is None


# ---------------------------------------------------------------------------
# Suricata.
# ---------------------------------------------------------------------------


def test_suricata_parses_flow_records_only() -> None:
    lines = _read("eve.json")
    flows = [f for f in (parse_suricata_line(line) for line in lines) if f is not None]
    # The middle line is an 'alert' event → skipped.
    assert len(flows) == 2

    first = flows[0]
    assert first["src_ip"] == "192.168.1.10"
    assert first["dst_ip"] == "192.168.1.20"
    assert first["dst_port"] == 443
    assert first["protocol"] == "tcp"
    f = first["features"]
    assert f["total_fwd_packets"] == 12
    assert f["total_backward_packets"] == 14
    assert f["bytes"] == 9600
    assert f["flow_bytes/s"] == 9600.0  # age=1s


def test_suricata_ignores_non_flow_and_malformed() -> None:
    assert parse_suricata_line('{"event_type":"alert","src_ip":"1.1.1.1"}') is None
    assert parse_suricata_line("not json at all") is None
    assert parse_suricata_line("") is None


def test_suricata_netflow_single_direction() -> None:
    line = (
        '{"timestamp":"2026-01-01T00:00:00+0000","event_type":"netflow",'
        '"src_ip":"10.0.0.1","src_port":1,"dest_ip":"10.0.0.2","dest_port":2,'
        '"proto":"UDP","netflow":{"pkts":7,"bytes":700,"age":2}}'
    )
    flow = parse_suricata_line(line)
    assert flow is not None
    assert flow["features"]["total_fwd_packets"] == 7
    assert flow["features"]["flow_packets/s"] == 3.5  # 7 / 2


# ---------------------------------------------------------------------------
# Format sniffing (pcap_replay).
# ---------------------------------------------------------------------------


def test_sniff_kind() -> None:
    assert sniff_kind('{"event_type":"flow"}') == "suricata"
    assert sniff_kind("#separator \\x09") == "zeek"
    assert sniff_kind("1700000000\t1.2.3.4") == "zeek"
