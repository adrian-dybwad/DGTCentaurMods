"""Driver interfaces for the self-contained e-paper framework."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import List, Tuple

from .framebuffer import FrameBuffer
from .scheduler import RefreshPlan

LOGGER = logging.getLogger(__name__)


class EPaperDriver(ABC):
    """Abstract driver responsible for issuing refresh commands."""

    async def connect(self) -> None:
        """Optional hook for initializing the hardware."""

    async def close(self) -> None:
        """Optional hook for cleaning up resources."""

    @abstractmethod
    async def refresh(self, plan: RefreshPlan, frame: FrameBuffer) -> None:
        """Execute the refresh plan."""


class SimulatedEPaperDriver(EPaperDriver):
    """Driver that logs refresh actions for demos and tests."""

    def __init__(self, *, latency: float = 0.05) -> None:
        self.latency = latency
        self.history: List[Tuple[str, int]] = []

    async def refresh(self, plan: RefreshPlan, frame: FrameBuffer) -> None:  # type: ignore[override]
        """Log the refresh and simulate panel latency."""
        region_count = len(plan.regions)
        self.history.append((plan.mode.value, region_count))
        LOGGER.info("Simulated refresh mode=%s regions=%s", plan.mode.value, region_count)
        if self.latency > 0:
            await asyncio.sleep(self.latency)

