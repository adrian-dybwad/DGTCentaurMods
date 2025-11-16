"""Driver interfaces for the self-contained e-paper framework."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from ctypes import CDLL, create_string_buffer
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None

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
        # Call reset before init to ensure clean state
        dll.reset()
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

        if plan.mode is RefreshMode.FULL:
            LOGGER.info("Issuing full hardware refresh.")
            payload = self._pack_full(pixels)
            buffer = create_string_buffer(payload)
            self._dll.display(buffer)
            return

        for region in plan.regions:
            logical_y0 = max(0, region.y)
            logical_y1 = min(self.height, region.y + region.height)
            if logical_y0 >= logical_y1:
                continue
            # Match legacy: expand to 8-pixel row boundaries, full width
            row_height = 8
            expanded_y0 = (logical_y0 // row_height) * row_height
            expanded_y1 = ((logical_y1 + row_height - 1) // row_height) * row_height
            # Calculate hardware coordinates (after rotation, top becomes bottom)
            hw_y0 = self._align_row(self.height - expanded_y1)
            hw_y1 = self._align_row_up(self.height - expanded_y0)
            if hw_y0 >= hw_y1:
                continue
            # Match legacy flow: crop logical region, rotate, convert
            payload = self._pack_region(pixels, expanded_y0, expanded_y1, hw_y0, hw_y1)
            buffer = create_string_buffer(payload)
            LOGGER.info("Issuing partial refresh logical_y=[%s-%s] hw_y=[%s-%s]", expanded_y0, expanded_y1, hw_y0, hw_y1)
            self._dll.displayRegion(hw_y0, hw_y1, buffer)

    def _rotate_pixels(self, pixels: Sequence[Sequence[int]]) -> List[List[int]]:
        if len(pixels) != self.height:
            raise ValueError("Pixel buffer height mismatch.")
        if not pixels:
            return []
        row_length = len(pixels[0])
        if row_length != self.width:
            raise ValueError("Pixel buffer width mismatch.")
        return [list(reversed(row)) for row in reversed(pixels)]

    def _pixels_to_image(self, pixels: Sequence[Sequence[int]]) -> "Image.Image":
        """Convert pixel array to PIL Image, matching legacy driver input format."""
        if Image is None:
            raise RuntimeError("PIL/Pillow required for hardware driver")
        img = Image.new("L", (self.width, self.height), color=255)
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                img.putpixel((x, y), value)
        return img.transpose(Image.ROTATE_180)

    def _convert_image(self, image: "Image.Image") -> bytes:
        """Convert PIL Image to bytes using exact legacy driver formula."""
        width, height = image.size
        buf = bytearray([0xFF] * ((width // 8) * height))
        mono = image.convert("1")
        pixels = mono.load()
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == 0:
                    buf[(x + y * width) // 8] &= ~(0x80 >> (x % 8))
        return bytes(buf)

    def _pack_full(self, pixels: Sequence[Sequence[int]]) -> bytes:
        """Pack entire framebuffer using PIL conversion to match legacy exactly."""
        img = self._pixels_to_image(pixels)
        return self._convert_image(img)

    def _pack_region(self, pixels: Sequence[Sequence[int]], logical_y0: int, logical_y1: int, hw_y0: int, hw_y1: int) -> bytes:
        """Match legacy flow exactly: crop logical region, rotate, convert."""
        if Image is None:
            raise RuntimeError("PIL/Pillow required for hardware driver")
        # Step 1: Create full image from pixels
        img = Image.new("L", (self.width, self.height), color=255)
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                img.putpixel((x, y), value)
        # Step 2: Crop to logical region (full width, partial height) - EXACTLY like legacy scheduler
        cropped = img.crop((0, logical_y0, self.width, logical_y1))
        # Step 3: Rotate the cropped image - EXACTLY like legacy _rotate_180
        rotated = cropped.transpose(Image.ROTATE_180)
        # Step 4: Convert using EXACT legacy formula - match byte-for-byte
        width, height = rotated.size
        buf = bytearray([0xFF] * (int(width / 8) * height))
        mono = rotated.convert("1")
        pix = mono.load()
        for y in range(height):
            for x in range(width):
                if pix[x, y] == 0:
                    buf[int((x + y * width) / 8)] &= ~(0x80 >> (x % 8))
        return bytes(buf)

    def _align_row(self, value: int) -> int:
        return max(0, (value // 8) * 8)

    def _align_row_up(self, value: int) -> int:
        return min(self.height, ((value + 7) // 8) * 8)

