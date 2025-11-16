from __future__ import annotations

import pathlib
import time

from PIL import Image

from ..driver_base import DriverBase


class SimulatorDriver(DriverBase):
    """Writes PNG snapshots for automated tests or headless environments."""

    def __init__(self) -> None:
        self._output_dir = pathlib.Path("/tmp/epaper-sim")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def init(self) -> None:
        return

    def reset(self) -> None:
        return

    def full_refresh(self, image: Image.Image) -> None:
        self._dump(image, "full")

    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        self._dump(image, f"partial_{y0}_{y1}")

    def sleep(self) -> None:
        return

    def shutdown(self) -> None:
        return

    def _dump(self, image: Image.Image, tag: str) -> None:
        timestamp = int(time.time() * 1000)
        self._counter += 1
        filename = self._output_dir / f"frame_{self._counter:05d}_{tag}_{timestamp}.png"
        image.save(filename)

