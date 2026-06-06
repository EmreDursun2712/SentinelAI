"""Scope enforcement — flows outside the authorized lab CIDRs are dropped."""

from __future__ import annotations

from collections.abc import Sequence
from ipaddress import IPv4Network, IPv6Network, ip_address


def flow_in_scope(
    flow: dict, allowed_cidrs: Sequence[IPv4Network | IPv6Network]
) -> bool:
    """True if either endpoint falls inside an allowed lab CIDR.

    A flow is in scope when at least one of its IPs is part of an authorized
    subnet — this keeps traffic that merely transits unrelated hosts out of the
    pipeline. With no CIDRs configured nothing is in scope (fail closed).
    """
    if not allowed_cidrs:
        return False
    for key in ("src_ip", "dst_ip"):
        raw = flow.get(key)
        if not raw:
            continue
        try:
            addr = ip_address(str(raw))
        except ValueError:
            continue
        for net in allowed_cidrs:
            if addr.version == net.version and addr in net:
                return True
    return False
