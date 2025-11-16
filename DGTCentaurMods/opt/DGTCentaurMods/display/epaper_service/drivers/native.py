from __future__ import annotations

import pathlib
import time
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
        """
        Perform a full screen refresh.
        
        The C library's display() function may return immediately after sending
        the command, but the hardware takes 1.5-2.0 seconds to complete the refresh.
        If the hardware is busy, the C library may return immediately without sending
        the command. We always wait the full refresh duration to ensure the hardware
        is ready for the next command.
        """
        from DGTCentaurMods.board.logging import log
        start_time = time.time()
        self._dll.display(self._convert(image))
        elapsed = time.time() - start_time
        # Always wait for full refresh duration (2.0s) to ensure hardware is ready
        # If C library returned quickly (< 2s), it may have detected hardware busy and
        # not sent the command, or the hardware refresh is still in progress
        if elapsed < 2.0:
            wait_time = 2.0 - elapsed
            log.info(f">>> NativeDriver.full_refresh() C library returned after {elapsed:.3f}s, waiting {wait_time:.3f}s for hardware refresh to complete")
            time.sleep(wait_time)
        else:
            log.info(f">>> NativeDriver.full_refresh() C library took {elapsed:.3f}s (hardware refresh should be complete)")

    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        self._dll.displayRegion(y0, y1, self._convert(image))

    def sleep(self) -> None:
        self._dll.sleepDisplay()

    def shutdown(self) -> None:
        self._dll.powerOffDisplay()

