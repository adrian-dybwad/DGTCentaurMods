"""Driver interfaces for the self-contained e-paper framework."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from ctypes import CDLL, c_int, create_string_buffer
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .framebuffer import FrameBuffer
from .scheduler import RefreshMode, RefreshPlan

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


class NativeEPaperDriver(EPaperDriver):
    """Driver that talks to the bundled epaperDriver.so shared object."""

    def __init__(
        self,
        *,
        width: int,
        height: int,
        library_path: Optional[Path | str] = None,
    ) -> None:
        if width % 8 != 0:
            raise ValueError("Hardware driver requires width divisible by 8.")
        self.width = width
        self.height = height
        self._library_path = Path(library_path) if library_path else Path(__file__).with_name("epaperDriver.so")
        self._dll: Optional[CDLL] = None

    async def connect(self) -> None:  # type: ignore[override]
        """Open the hardware and run the initialization sequence."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._initialize)

    async def close(self) -> None:  # type: ignore[override]
        """Put the display to sleep and release resources."""
        if not self._dll:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._shutdown)

    async def refresh(self, plan: RefreshPlan, frame: FrameBuffer) -> None:  # type: ignore[override]
        """Execute a refresh plan against the UC8151 backend."""
        if plan.mode is RefreshMode.IDLE:
            return
        if not self._dll:
            raise RuntimeError("Hardware driver not connected.")
        pixels = frame.get_pixels()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._refresh_blocking, plan, pixels)

    def _initialize(self) -> None:
        if self._dll:
            return
        if not self._library_path.exists():
            raise FileNotFoundError(f"E-paper shared library not found at {self._library_path}")
        dll = CDLL(str(self._library_path))
        dll.openDisplay()
        dll.init()
        self._dll = dll

    def _shutdown(self) -> None:
        if not self._dll:
            return
        self._dll.sleepDisplay()
        self._dll.powerOffDisplay()
        self._dll = None

    def _refresh_blocking(self, plan: RefreshPlan, pixels: Sequence[Sequence[int]]) -> None:
        if not self._dll:
            raise RuntimeError("Hardware driver not connected.")
        rotated = self._rotate_pixels(pixels)

        if plan.mode is RefreshMode.FULL:
            LOGGER.info("Issuing full hardware refresh.")
            payload = self._pack_rows(rotated, 0, self.height)
            buffer = create_string_buffer(payload)
            self._dll.display(buffer)
            return

        for region in plan.regions:
            logical_y0 = max(0, region.y)
            logical_y1 = min(self.height, region.y + region.height)
            if logical_y0 >= logical_y1:
                continue
            hw_y0 = self._align_row(self.height - logical_y1)
            hw_y1 = self._align_row_up(self.height - logical_y0)
            if hw_y0 >= hw_y1:
                continue
            payload = self._pack_rows(rotated, hw_y0, hw_y1)
            buffer = create_string_buffer(payload)
            LOGGER.info("Issuing partial refresh y0=%s y1=%s", hw_y0, hw_y1)
            self._dll.displayRegion(c_int(hw_y0), c_int(hw_y1), buffer)

    def _rotate_pixels(self, pixels: Sequence[Sequence[int]]) -> List[List[int]]:
        if len(pixels) != self.height:
            raise ValueError("Pixel buffer height mismatch.")
        if not pixels:
            return []
        row_length = len(pixels[0])
        if row_length != self.width:
            raise ValueError("Pixel buffer width mismatch.")
        return [list(reversed(row)) for row in reversed(pixels)]

    def _pack_rows(self, pixels: Sequence[Sequence[int]], y0: int, y1: int) -> bytes:
        stride = self.width // 8
        height = y1 - y0
        buf = bytearray([0xFF] * (stride * height))
        for y in range(y0, y1):
            row = pixels[y]
            for x in range(self.width):
                idx = (y - y0) * stride + (x // 8)
                mask = 0x80 >> (x % 8)
                if row[x] < 128:
                    buf[idx] &= ~mask
                else:
                    buf[idx] |= mask
        return bytes(buf)

    def _align_row(self, value: int) -> int:
        return max(0, (value // 8) * 8)

    def _align_row_up(self, value: int) -> int:
        return min(self.height, ((value + 7) // 8) * 8)

