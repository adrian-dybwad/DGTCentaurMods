from __future__ import annotations

import pathlib
import time
from ctypes import CDLL, c_int

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
        # Configure readBusy function signature
        # Note: readBusy() likely returns 0 when busy (LOW) and 1 when idle (HIGH)
        # based on UC8151 BUSY_N signal (LOW=busy, HIGH=idle)
        self._dll.readBusy.argtypes = []
        self._dll.readBusy.restype = c_int

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
        """
        Initialize the display hardware.
        
        Per UC8151 reference designs, init operations may require waiting for
        hardware to be ready. The C library should handle this internally.
        
        CRITICAL FIX: Do not wait for idle after init() because readBusy() returns
        garbage values during initialization. The C library's init() should handle
        all timing internally.
        """
        self._dll.init()
        # Do not wait for idle after init() - readBusy() returns garbage values
        # during initialization. The C library should handle all timing internally.

    def reset(self) -> None:
        """
        Reset the display hardware.
        
        Per UC8151 reference designs, reset operations may require waiting for
        hardware to be ready. The C library should handle this internally.
        
        CRITICAL FIX: Do not wait for idle after reset() because readBusy() returns
        garbage values during reset. The C library's reset() should handle all
        timing internally.
        """
        self._dll.reset()
        # Do not wait for idle after reset() - readBusy() returns garbage values
        # during reset. The C library should handle all timing internally.

    def full_refresh(self, image: Image.Image) -> None:
        """
        Perform a full screen refresh.
        
        CRITICAL FIX: readBusy() is a blocking wait function, not a status check.
        It doesn't return the busy status - it just waits until idle.
        The C library's display() function handles busy checking internally.
        
        We rely on the C library to handle all busy signal checking internally.
        """
        from DGTCentaurMods.board.logging import log
        # Send display command - C library handles busy checking internally
        log.info(">>> NativeDriver.full_refresh() sending display command (C library handles busy checking)")
        start_time = time.time()
        self._dll.display(self._convert(image))
        cmd_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.full_refresh() display() returned after {cmd_elapsed:.3f}s")
        
        # Note: display() should block until hardware refresh completes
        # If it returns too quickly (< 1.5s), the hardware may not have refreshed
        if cmd_elapsed < 1.0:
            log.warning(f">>> NativeDriver.full_refresh() display() returned too quickly ({cmd_elapsed:.3f}s) - hardware may not have refreshed")
        
        total_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.full_refresh() complete, total duration={total_elapsed:.3f}s")

    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        """
        Perform a partial screen refresh.
        
        CRITICAL FIX: readBusy() is a blocking wait function, not a status check.
        It doesn't return the busy status - it just waits until idle.
        The C library's displayRegion() function handles busy checking internally.
        
        We rely on the C library to handle all busy signal checking internally.
        """
        from DGTCentaurMods.board.logging import log
        # Send partial refresh command - C library handles busy checking internally
        log.info(f">>> NativeDriver.partial_refresh() sending displayRegion command (y0={y0}, y1={y1}, C library handles busy checking)")
        start_time = time.time()
        self._dll.displayRegion(y0, y1, self._convert(image))
        cmd_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.partial_refresh() displayRegion() returned after {cmd_elapsed:.3f}s")
        
        # Note: displayRegion() should block until hardware refresh completes
        # If it returns too quickly (< 0.26s), the hardware may not have refreshed
        if cmd_elapsed < 0.2:
            log.warning(f">>> NativeDriver.partial_refresh() displayRegion() returned too quickly ({cmd_elapsed:.3f}s) - hardware may not have refreshed")
        
        total_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.partial_refresh() complete, total duration={total_elapsed:.3f}s")

    def sleep(self) -> None:
        """
        Put the display into sleep mode.
        
        CRITICAL FIX: readBusy() is a blocking wait function, not a status check.
        The C library's sleepDisplay() function should handle any necessary waiting.
        """
        from DGTCentaurMods.board.logging import log
        log.info(">>> NativeDriver.sleep() calling sleepDisplay() (C library handles busy checking)")
        self._dll.sleepDisplay()

    def shutdown(self) -> None:
        """
        Power off the display.
        
        CRITICAL FIX: readBusy() is a blocking wait function, not a status check.
        The C library's powerOffDisplay() function should handle any necessary waiting.
        """
        from DGTCentaurMods.board.logging import log
        log.info(">>> NativeDriver.shutdown() calling powerOffDisplay() (C library handles busy checking)")
        self._dll.powerOffDisplay()

