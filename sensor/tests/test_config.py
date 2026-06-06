"""Config + safety-gate tests."""

from __future__ import annotations

import pytest

from sentinelai_sensor.config import SensorConfig, SensorConfigError

BASE_ENV = {
    "SENTINEL_SENSOR_ENABLED": "true",
    "SENTINEL_SENSOR_MODE": "zeek",
    "SENTINEL_SENSOR_INPUT_PATH": "/logs/conn.log",
    "SENTINEL_SENSOR_ALLOWED_CIDRS": "192.168.0.0/16, 10.0.0.0/8",
    "SENTINEL_SENSOR_API_URL": "http://backend:8000/",
    "SENTINEL_SENSOR_API_TOKEN": "tok",
}


def test_from_env_parses_all_fields() -> None:
    cfg = SensorConfig.from_env(BASE_ENV)
    assert cfg.enabled is True
    assert cfg.mode == "zeek"
    assert cfg.input_path == "/logs/conn.log"
    assert [str(c) for c in cfg.allowed_cidrs] == ["192.168.0.0/16", "10.0.0.0/8"]
    assert cfg.api_url == "http://backend:8000"  # trailing slash stripped
    assert cfg.batch_size == 100
    assert cfg.interval_seconds == 2.0
    cfg.validate()  # should not raise


def test_disabled_by_default_refuses_to_start() -> None:
    cfg = SensorConfig.from_env({})  # nothing set → disabled
    assert cfg.enabled is False
    with pytest.raises(SensorConfigError, match="ENABLED"):
        cfg.validate()


def test_refuses_without_allowed_cidrs() -> None:
    env = dict(BASE_ENV)
    env.pop("SENTINEL_SENSOR_ALLOWED_CIDRS")
    cfg = SensorConfig.from_env(env)
    with pytest.raises(SensorConfigError, match="ALLOWED_CIDRS"):
        cfg.validate()


def test_rejects_unknown_mode() -> None:
    env = dict(BASE_ENV, SENTINEL_SENSOR_MODE="packet_capture")
    with pytest.raises(SensorConfigError, match="MODE"):
        SensorConfig.from_env(env).validate()


def test_requires_token_and_url() -> None:
    env = dict(BASE_ENV)
    env.pop("SENTINEL_SENSOR_API_TOKEN")
    with pytest.raises(SensorConfigError, match="API_TOKEN"):
        SensorConfig.from_env(env).validate()
