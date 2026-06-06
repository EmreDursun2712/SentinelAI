"""Shared base class for agent modules.

Agents are plain async classes wired to the in-process event bus. They share state
through the database; this base only defines the lifecycle contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.events import EventBus, get_event_bus
from app.core.logging import get_logger


class Agent(ABC):
    name: str = "agent"

    def __init__(self, bus: EventBus | None = None) -> None:
        self.bus = bus or get_event_bus()
        self.logger = get_logger(self.name)

    @abstractmethod
    def register(self) -> None:
        """Subscribe to relevant events on the bus."""
