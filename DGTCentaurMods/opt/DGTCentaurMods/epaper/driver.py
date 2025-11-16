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
        payload = self._pack_pixels(pixels)
        buffer = create_string_buffer(payload)

        if plan.mode is RefreshMode.FULL:
            LOGGER.info("Issuing full hardware refresh.")
            self._dll.display(buffer)
            return

        for region in plan.regions:
            y0 = max(0, min(self.height, region.y))
            y1 = max(y0, min(self.height, region.y + region.height))
            if y0 == y1:
                continue
            LOGGER.info("Issuing partial refresh y0=%s y1=%s", y0, y1)
            self._dll.displayRegion(c_int(y0), c_int(y1), buffer)

    def _pack_pixels(self, pixels: Sequence[Sequence[int]]) -> bytes:
        if len(pixels) != self.height:
            raise ValueError("Pixel buffer height mismatch.")
        if not pixels:
            return b""
        row_length = len(pixels[0])
        if row_length != self.width:
            raise ValueError("Pixel buffer width mismatch.")
        stride = self.width // 8
        buf = bytearray([0xFF] * (stride * self.height))
        for y in range(self.height):
            row = pixels[y]
            if len(row) != self.width:
                raise ValueError("Inconsistent row width in framebuffer snapshot.")
            for x in range(self.width):
                idx = y * stride + (x // 8)
                mask = 0x80 >> (x % 8)
                if row[x] < 128:
                    buf[idx] &= ~mask
                else:
                    buf[idx] |= mask
        return bytes(buf)

