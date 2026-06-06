"""Scope-filtering safety tests."""

from __future__ import annotations

from ipaddress import ip_network

from sentinelai_sensor.safety import flow_in_scope

LAB = (ip_network("192.168.0.0/16"), ip_network("10.0.0.0/8"))


def test_in_scope_when_src_in_lab() -> None:
    assert flow_in_scope({"src_ip": "192.168.1.10", "dst_ip": "8.8.8.8"}, LAB)


def test_in_scope_when_dst_in_lab() -> None:
    assert flow_in_scope({"src_ip": "1.2.3.4", "dst_ip": "10.5.6.7"}, LAB)


def test_out_of_scope_when_neither_in_lab() -> None:
    assert not flow_in_scope({"src_ip": "1.2.3.4", "dst_ip": "8.8.8.8"}, LAB)


def test_no_cidrs_means_nothing_in_scope() -> None:
    assert not flow_in_scope({"src_ip": "192.168.1.1", "dst_ip": "10.0.0.1"}, ())


def test_invalid_or_missing_ip_is_safe() -> None:
    assert not flow_in_scope({"src_ip": "not-an-ip"}, LAB)
    assert not flow_in_scope({}, LAB)
