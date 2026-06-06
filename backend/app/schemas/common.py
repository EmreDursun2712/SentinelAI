"""Shared schema helpers."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address
from typing import Annotated, Any

from pydantic import BeforeValidator


def _ip_to_string(value: Any) -> Any:
    if isinstance(value, IPv4Address | IPv6Address):
        return str(value)
    return value


IpString = Annotated[str, BeforeValidator(_ip_to_string)]
