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
        # Configure readBusy function signature (returns int: 0=idle, non-zero=busy)
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
        self._dll.init()

    def reset(self) -> None:
        self._dll.reset()

    def _wait_for_idle(self, timeout: float = 5.0) -> bool:
        """
        Wait for hardware to become idle (not busy) by polling the BUSY signal.
        
        This conforms to e-paper display reference designs which require checking
        the BUSY pin before sending commands.
        
        Returns:
            True if hardware became idle, False if timeout
        """
        from DGTCentaurMods.board.logging import log
        start_time = time.time()
        while self._dll.readBusy() != 0:
            if time.time() - start_time > timeout:
                log.warning(f">>> NativeDriver._wait_for_idle() timeout after {timeout}s")
                return False
            time.sleep(0.01)  # Poll every 10ms to avoid excessive CPU usage
        elapsed = time.time() - start_time
        if elapsed > 0.01:
            log.info(f">>> NativeDriver._wait_for_idle() hardware became idle after {elapsed:.3f}s")
        return True

    def full_refresh(self, image: Image.Image) -> None:
        """
        Perform a full screen refresh.
        
        Conforms to e-paper display reference designs:
        1. Wait for hardware to be idle (not busy) before sending command
        2. Send the display command
        3. Wait for hardware to complete the refresh (become idle again)
        
        This ensures the hardware is ready before each command and prevents
        corruption from rapid successive refreshes.
        """
        from DGTCentaurMods.board.logging import log
        # Step 1: Wait for hardware to be ready (conforms to reference designs)
        log.info(">>> NativeDriver.full_refresh() waiting for hardware to be idle before sending command")
        if not self._wait_for_idle(timeout=5.0):
            log.error(">>> NativeDriver.full_refresh() hardware did not become idle, proceeding anyway")
        
        # Step 2: Send display command
        log.info(">>> NativeDriver.full_refresh() hardware is idle, sending display command")
        start_time = time.time()
        self._dll.display(self._convert(image))
        cmd_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.full_refresh() display() returned after {cmd_elapsed:.3f}s")
        
        # Step 3: Wait for hardware to complete refresh (conforms to reference designs)
        log.info(">>> NativeDriver.full_refresh() waiting for hardware to complete refresh")
        if not self._wait_for_idle(timeout=5.0):
            log.error(">>> NativeDriver.full_refresh() hardware did not complete refresh within timeout")
        total_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.full_refresh() complete, total duration={total_elapsed:.3f}s")

    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        self._dll.displayRegion(y0, y1, self._convert(image))

    def sleep(self) -> None:
        self._dll.sleepDisplay()

    def shutdown(self) -> None:
        self._dll.powerOffDisplay()

