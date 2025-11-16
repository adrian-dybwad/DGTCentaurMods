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
        
        According to UC8151 datasheet: BUSY_N is LOW when busy, HIGH when idle.
        The readBusy() function may return 0 when idle (HIGH) or non-zero when busy (LOW).
        We need to determine the actual return value semantics.
        
        Returns:
            True if hardware became idle, False if timeout
        """
        from DGTCentaurMods.board.logging import log
        start_time = time.time()
        # First, check what readBusy() returns to understand the semantics
        initial_value = self._dll.readBusy()
        log.info(f">>> NativeDriver._wait_for_idle() readBusy() returned {initial_value} (0=idle, non-zero=busy)")
        
        # Try both interpretations: maybe 0=busy and 1=idle, or maybe 0=idle and 1=busy
        # Based on UC8151: BUSY_N LOW = busy, HIGH = idle
        # Most GPIO reads return 0 for LOW and 1 for HIGH, so readBusy() likely returns:
        # 0 = LOW = busy, 1 = HIGH = idle
        # But we need to verify by waiting for the value to change
        
        # Wait for readBusy() to return 1 (assuming 1=idle, 0=busy)
        # If it times out, try the opposite interpretation
        while self._dll.readBusy() == 0:  # Wait for non-zero (assuming 1=idle)
            if time.time() - start_time > timeout:
                # Try opposite interpretation: maybe 0=idle?
                log.warning(f">>> NativeDriver._wait_for_idle() timeout waiting for non-zero, trying opposite interpretation")
                # If we've been waiting for non-zero and it timed out, maybe 0 actually means idle
                # Check one more time
                final_value = self._dll.readBusy()
                if final_value == 0:
                    log.info(f">>> NativeDriver._wait_for_idle() readBusy() is 0, treating as idle (0=idle interpretation)")
                    return True
                return False
            time.sleep(0.01)  # Poll every 10ms to avoid excessive CPU usage
        
        elapsed = time.time() - start_time
        final_value = self._dll.readBusy()
        log.info(f">>> NativeDriver._wait_for_idle() hardware became idle after {elapsed:.3f}s (readBusy()={final_value})")
        return True

    def full_refresh(self, image: Image.Image) -> None:
        """
        Perform a full screen refresh.
        
        Conforms to e-paper display reference designs:
        1. Send the display command (C library should check busy signal internally)
        2. Wait for hardware to complete the refresh (become idle)
        
        Note: We don't wait for idle BEFORE sending because:
        - The C library's display() function should handle busy checking internally
        - After init, hardware may still be busy from init refresh
        - We only need to wait AFTER sending to ensure refresh completes
        """
        from DGTCentaurMods.board.logging import log
        # Step 1: Send display command (C library handles busy checking)
        log.info(">>> NativeDriver.full_refresh() sending display command")
        start_time = time.time()
        self._dll.display(self._convert(image))
        cmd_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.full_refresh() display() returned after {cmd_elapsed:.3f}s")
        
        # Step 2: Wait for hardware to complete refresh (conforms to reference designs)
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

