"""Runner tests: batching, scope filtering, and pcap_replay end-to-end."""

from __future__ import annotations

from ipaddress import ip_network
from pathlib import Path

from sentinelai_sensor.config import SensorConfig
from sentinelai_sensor.runner import IDLE, pump, records_from

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

LAB = (ip_network("192.168.0.0/16"), ip_network("10.0.0.0/8"))


class FakeClient:
    def __init__(self) -> None:
        self.batches: list[list[dict]] = []

    def post_flows(self, flows):
        self.batches.append(list(flows))
        return {"inserted": len(flows)}


def _cfg(**kw) -> SensorConfig:
    base = dict(
        enabled=True,
        mode="pcap_replay",
        input_path=str(SAMPLES / "conn.log"),
        allowed_cidrs=LAB,
        api_url="http://x",
        api_token="t",
        batch_size=2,
        interval_seconds=2.0,
    )
    base.update(kw)
    return SensorConfig(**base)


def test_pump_batches_by_size_and_flushes_remainder() -> None:
    client = FakeClient()
    records = [
        {"src_ip": "192.168.1.1", "dst_ip": "8.8.8.8"},
        {"src_ip": "192.168.1.2", "dst_ip": "8.8.8.8"},
        {"src_ip": "10.0.0.1", "dst_ip": "8.8.8.8"},
    ]
    posted = pump(records, _cfg(batch_size=2), client)
    assert posted == 3
    assert [len(b) for b in client.batches] == [2, 1]  # full batch, then remainder


def test_pump_drops_out_of_scope_flows() -> None:
    client = FakeClient()
    records = [
        {"src_ip": "1.2.3.4", "dst_ip": "8.8.8.8"},  # out of scope
        {"src_ip": "192.168.1.9", "dst_ip": "9.9.9.9"},  # in scope
    ]
    posted = pump(records, _cfg(batch_size=10), client)
    assert posted == 1
    assert client.batches == [[{"src_ip": "192.168.1.9", "dst_ip": "9.9.9.9"}]]


def test_pump_flushes_partial_batch_on_interval() -> None:
    client = FakeClient()
    clock = {"t": 0.0}
    cfg = _cfg(batch_size=100, interval_seconds=2.0)
    records = [
        {"src_ip": "192.168.1.1", "dst_ip": "8.8.8.8"},
        IDLE,  # idle tick #1 — only 1s elapsed, not yet due
        IDLE,  # idle tick #2 — 3s elapsed, interval passed → flush
    ]
    # clock() calls: init last_flush, idle1 cond, idle2 cond, flush-in-idle2, final flush
    ticks = iter([0.0, 1.0, 3.0, 3.0, 3.0])

    def fake_clock():
        return next(ticks)

    posted = pump(records, cfg, client, now=fake_clock)
    assert posted == 1
    assert len(client.batches) == 1


def test_pcap_replay_reads_sample_file_end_to_end() -> None:
    client = FakeClient()
    cfg = _cfg(mode="pcap_replay", input_path=str(SAMPLES / "conn.log"), batch_size=100)
    posted = pump(records_from(cfg), cfg, client)
    # 3 flows in the sample, all within lab CIDRs (192.168/10.x endpoints).
    assert posted == 3


def test_pcap_replay_suricata_file() -> None:
    client = FakeClient()
    cfg = _cfg(mode="pcap_replay", input_path=str(SAMPLES / "eve.json"), batch_size=100)
    posted = pump(records_from(cfg), cfg, client)
    assert posted == 2  # 2 flow events (alert line skipped)
