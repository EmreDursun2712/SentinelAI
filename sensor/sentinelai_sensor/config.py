"""Sensor configuration + start-up safety gates.

Everything here is stdlib-only so the parser/safety/config test suite runs
without installing the HTTP client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_network

VALID_MODES = ("zeek", "suricata", "pcap_replay")

_TRUTHY = {"1", "true", "yes", "on"}


class SensorConfigError(RuntimeError):
    """Raised when the sensor is misconfigured or a safety gate is not satisfied."""


@dataclass(frozen=True)
class SensorConfig:
    enabled: bool
    mode: str
    input_path: str
    allowed_cidrs: tuple[IPv4Network | IPv6Network, ...]
    api_url: str
    api_token: str
    batch_size: int
    interval_seconds: float

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> SensorConfig:
        env = env if env is not None else dict(os.environ)

        def get(key: str, default: str = "") -> str:
            return (env.get(key) or default).strip()

        raw_cidrs = get("SENTINEL_SENSOR_ALLOWED_CIDRS")
        cidrs: list[IPv4Network | IPv6Network] = []
        for chunk in raw_cidrs.split(","):
            chunk = chunk.strip()
            if chunk:
                cidrs.append(ip_network(chunk, strict=False))

        return SensorConfig(
            enabled=get("SENTINEL_SENSOR_ENABLED", "false").lower() in _TRUTHY,
            mode=get("SENTINEL_SENSOR_MODE").lower(),
            input_path=get("SENTINEL_SENSOR_INPUT_PATH"),
            allowed_cidrs=tuple(cidrs),
            api_url=get("SENTINEL_SENSOR_API_URL").rstrip("/"),
            api_token=get("SENTINEL_SENSOR_API_TOKEN"),
            batch_size=int(get("SENTINEL_SENSOR_BATCH_SIZE", "100")),
            interval_seconds=float(get("SENTINEL_SENSOR_INTERVAL_SECONDS", "2")),
        )

    def validate(self) -> None:
        """Enforce the start-up safety gates. Raises ``SensorConfigError``.

        These are the hard guardrails: the sensor will not run unless it is
        explicitly enabled AND scoped to authorized lab subnets.
        """
        if not self.enabled:
            raise SensorConfigError(
                "Refusing to start: SENTINEL_SENSOR_ENABLED is not true. "
                "Live ingestion is OFF by default."
            )
        if self.mode not in VALID_MODES:
            raise SensorConfigError(
                f"SENTINEL_SENSOR_MODE must be one of {VALID_MODES}; got {self.mode!r}."
            )
        if not self.input_path:
            raise SensorConfigError("SENTINEL_SENSOR_INPUT_PATH is required.")
        if not self.allowed_cidrs:
            raise SensorConfigError(
                "Refusing to tail/replay without SENTINEL_SENSOR_ALLOWED_CIDRS — "
                "authorized lab subnets must be configured explicitly."
            )
        if not self.api_url:
            raise SensorConfigError("SENTINEL_SENSOR_API_URL is required.")
        if not self.api_token:
            raise SensorConfigError("SENTINEL_SENSOR_API_TOKEN is required.")
        if self.batch_size < 1:
            raise SensorConfigError("SENTINEL_SENSOR_BATCH_SIZE must be >= 1.")
        if self.interval_seconds <= 0:
            raise SensorConfigError("SENTINEL_SENSOR_INTERVAL_SECONDS must be > 0.")
