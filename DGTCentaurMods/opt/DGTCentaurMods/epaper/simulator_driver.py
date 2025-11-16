"""
Simulator driver for testing without hardware.

Saves PNG snapshots to /tmp/epaper-sim/ instead of updating hardware.
"""

import pathlib
import time
from typing import Optional

from PIL import Image


class SimulatorDriver:
    """
    Simulator driver that saves PNG files instead of updating hardware.
    
    Useful for testing and development without physical hardware.
    """

    def __init__(self) -> None:
        self.width = 128
        self.height = 296
        self._output_dir = pathlib.Path("/tmp/epaper-sim")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def init(self) -> None:
        """Initialize simulator (no-op)."""
        pass

    def reset(self) -> None:
        """Reset simulator (no-op)."""
        pass

    def full_refresh(self, image: Image.Image) -> None:
        """Save full refresh as PNG."""
        self._save_image(image, "full")

    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        """Save partial refresh as PNG."""
        self._save_image(image, f"partial_{y0}_{y1}")

    def sleep(self) -> None:
        """Sleep simulator (no-op)."""
        pass

    def shutdown(self) -> None:
        """Shutdown simulator (no-op)."""
        pass

    def _save_image(self, image: Image.Image, tag: str) -> None:
        """Save image to output directory."""
        timestamp = int(time.time() * 1000)
        self._counter += 1
        filename = self._output_dir / f"frame_{self._counter:05d}_{tag}_{timestamp}.png"
        image.save(filename)
        print(f"[Simulator] Saved {filename}")

