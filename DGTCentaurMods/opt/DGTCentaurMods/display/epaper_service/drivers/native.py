from __future__ import annotations

import pathlib
from ctypes import CDLL

from PIL import Image

from ..driver_base import DriverBase


class NativeDriver(DriverBase):
    """
    Wraps the existing epaperDriver.so shared library.

    The shared object already handles SPI communication with the panel.
    """

    def __init__(self) -> None:
        # epaperDriver.so still lives alongside display modules (../epaperDriver.so)
        lib_path = pathlib.Path(__file__).resolve().parents[2] / "epaperDriver.so"
        if not lib_path.exists():
            raise FileNotFoundError(f"Native ePaper driver not found at {lib_path}")
        self._dll = CDLL(str(lib_path))
        self._dll.openDisplay()

    def _convert(self, image: Image.Image) -> bytes:
        width, height = image.size
        buf = [0xFF] * (int(width / 8) * height)
        mono = image.convert("1")
        pixels = mono.load()
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == 0:
                    buf[int((x + y * width) / 8)] &= ~(0x80 >> (x % 8))
        return bytes(buf)

    def init(self) -> None:
        self._dll.init()

    def reset(self) -> None:
        self._dll.reset()

    def full_refresh(self, image: Image.Image) -> None:
        self._dll.display(self._convert(image))

    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        self._dll.displayRegion(y0, y1, self._convert(image))

    def sleep(self) -> None:
        self._dll.sleepDisplay()

    def shutdown(self) -> None:
        self._dll.powerOffDisplay()

