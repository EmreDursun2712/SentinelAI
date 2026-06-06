"""Sensor entrypoint: ``python -m sentinelai_sensor``.

Loads config from the environment, enforces the safety gates, and runs. Exits
non-zero with a clear message if a guardrail is not satisfied.
"""

from __future__ import annotations

import logging
import sys

from .client import BackendClient
from .config import SensorConfig, SensorConfigError
from .runner import run


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("sentinelai.sensor")

    config = SensorConfig.from_env()
    try:
        config.validate()
    except SensorConfigError as exc:
        log.error("refusing to start: %s", exc)
        return 2

    client = BackendClient(config.api_url, config.api_token)
    try:
        run(config, client)
    except KeyboardInterrupt:
        log.info("sensor stopped")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
