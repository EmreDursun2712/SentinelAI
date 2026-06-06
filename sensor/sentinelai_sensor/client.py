"""Thin HTTP client that posts flow batches to the SentinelAI backend."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("sentinelai.sensor.client")


class BackendClient:
    def __init__(self, api_url: str, token: str, *, timeout: float = 10.0) -> None:
        self._url = api_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    def post_flows(self, flows: list[dict[str, Any]]) -> dict[str, Any]:
        """POST a batch to /api/v1/ingest/flows. Raises on non-2xx."""
        resp = httpx.post(
            f"{self._url}/api/v1/ingest/flows",
            json={"flows": flows},
            headers=self._headers,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()
