"""Tail flow logs, filter to lab scope, batch, and post to the backend.

The batching loop (``pump``) is deliberately decoupled from file I/O so it can
be unit-tested with a plain iterable + a fake client. ``None`` items in the
record stream are idle ticks that let the loop flush a partial batch on the
configured interval.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator
from typing import Any, Protocol

from .config import SensorConfig
from .parsers import make_parser, sniff_kind
from .safety import flow_in_scope

logger = logging.getLogger("sentinelai.sensor")

# Sentinel for an idle tick (no new data) so pump can flush on interval.
IDLE = None


class _Poster(Protocol):
    def post_flows(self, flows: list[dict[str, Any]]) -> dict[str, Any]: ...


def pump(
    records: Iterable[dict[str, Any] | None],
    config: SensorConfig,
    client: _Poster,
    *,
    now: object = time.monotonic,
) -> int:
    """Consume parsed records, drop out-of-scope flows, batch + post in scope.

    Returns the total number of flows posted. Flushes any remainder when the
    record stream ends (finite inputs like pcap_replay).
    """
    clock = now  # injectable for tests
    batch: list[dict[str, Any]] = []
    posted = 0
    last_flush = clock()  # type: ignore[operator]

    def flush() -> None:
        nonlocal batch, posted, last_flush
        if batch:
            result = client.post_flows(batch)
            posted += len(batch)
            logger.info(
                "posted %d flow(s); backend inserted=%s",
                len(batch),
                result.get("inserted"),
            )
            batch = []
        last_flush = clock()  # type: ignore[operator]

    for rec in records:
        if rec is IDLE:
            if batch and (clock() - last_flush) >= config.interval_seconds:  # type: ignore[operator]
                flush()
            continue
        if not flow_in_scope(rec, config.allowed_cidrs):
            continue  # out of authorized scope — dropped (metadata-only log)
        batch.append(rec)
        if len(batch) >= config.batch_size:
            flush()
    flush()
    return posted


def tail_lines(path: str, *, follow: bool, poll: float = 0.25) -> Iterator[str | None]:
    """Yield lines from ``path``. When ``follow``, yields IDLE on no new data and
    keeps going; otherwise stops at EOF (one-shot replay)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        while True:
            line = fh.readline()
            if line:
                yield line.rstrip("\n")
                continue
            if not follow:
                return
            yield IDLE
            time.sleep(poll)


def records_from(config: SensorConfig) -> Iterator[dict[str, Any] | None]:
    """Produce parsed records for the configured mode."""
    follow = config.mode in ("zeek", "suricata")
    if config.mode == "pcap_replay":
        kind = _sniff_file(config.input_path)
    else:
        kind = config.mode
    parse = make_parser(kind)
    for line in tail_lines(config.input_path, follow=follow):
        if line is IDLE:
            yield IDLE
            continue
        flow = parse(line)
        if flow is not None:
            yield flow


def _sniff_file(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.strip():
                return sniff_kind(line)
    return "zeek"


def run(config: SensorConfig, client: _Poster) -> int:
    """Validate safety gates and run the sensor for the configured mode."""
    config.validate()
    logger.info(
        "starting sensor: mode=%s input=%s allowed_cidrs=%s batch_size=%d",
        config.mode,
        config.input_path,
        ",".join(str(c) for c in config.allowed_cidrs),
        config.batch_size,
    )
    return pump(records_from(config), config, client)
