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
        """
        self._dll.init()
        # Wait for hardware to be ready after init
        # Some init sequences perform refresh operations that need to complete
        if not self._wait_for_idle(timeout=5.0):
            from DGTCentaurMods.board.logging import log
            log.warning("Hardware did not become idle after init() - may still be initializing")

    def reset(self) -> None:
        """
        Reset the display hardware.
        
        Per UC8151 reference designs, reset operations may require waiting for
        hardware to be ready. The C library should handle this internally.
        """
        self._dll.reset()
        # Wait for hardware to be ready after reset
        # Reset sequences may take time to complete
        if not self._wait_for_idle(timeout=5.0):
            from DGTCentaurMods.board.logging import log
            log.warning("Hardware did not become idle after reset() - may still be resetting")

    def _wait_for_idle(self, timeout: float = 5.0) -> bool:
        """
        Wait for hardware to become idle (not busy) by polling the BUSY signal.
        
        According to UC8151 datasheet: BUSY_N is LOW when busy, HIGH when idle.
        GPIO reads typically return 0 for LOW and 1 for HIGH, so:
        - readBusy() returns 0 when busy (LOW)
        - readBusy() returns 1 when idle (HIGH)
        
        Returns:
            True if hardware became idle, False if timeout
        """
        from DGTCentaurMods.board.logging import log
        start_time = time.time()
        poll_count = 0
        while True:
            busy_value = self._dll.readBusy()
            poll_count += 1
            
            # Check if hardware is idle (1 = HIGH = idle)
            # Only accept valid return values (0 or 1)
            if busy_value == 1:
                elapsed = time.time() - start_time
                if elapsed > 0.01:
                    log.info(f">>> NativeDriver._wait_for_idle() hardware became idle after {elapsed:.3f}s (polled {poll_count} times)")
                return True
            
            # Check for timeout
            if time.time() - start_time > timeout:
                log.error(f">>> NativeDriver._wait_for_idle() timeout after {timeout}s (readBusy()={busy_value}, polled {poll_count} times)")
                return False
            
            time.sleep(0.01)  # Poll every 10ms to avoid excessive CPU usage

    def full_refresh(self, image: Image.Image) -> None:
        """
        Perform a full screen refresh.
        
        Conforms to e-paper display reference designs:
        1. Wait for hardware to be idle (ready for new command)
        2. Send the display command
        3. Wait for hardware to complete the refresh (become idle again)
        """
        from DGTCentaurMods.board.logging import log
        # Step 1: Wait for hardware to be ready (prevents C library from returning immediately)
        log.info(">>> NativeDriver.full_refresh() waiting for hardware to be idle before sending command")
        if not self._wait_for_idle(timeout=5.0):
            raise RuntimeError("Hardware did not become idle before full_refresh()")
        
        # Step 2: Send display command
        log.info(">>> NativeDriver.full_refresh() sending display command")
        start_time = time.time()
        self._dll.display(self._convert(image))
        cmd_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.full_refresh() display() returned after {cmd_elapsed:.3f}s")
        
        # Step 3: Wait for hardware to complete refresh
        log.info(">>> NativeDriver.full_refresh() waiting for hardware to complete refresh")
        if not self._wait_for_idle(timeout=5.0):
            raise RuntimeError("Hardware did not complete refresh within timeout")
        total_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.full_refresh() complete, total duration={total_elapsed:.3f}s")

    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        """
        Perform a partial screen refresh.
        
        Conforms to e-paper display reference designs:
        1. Wait for hardware to be idle (ready for new command)
        2. Send the partial refresh command
        3. Wait for hardware to complete the refresh (become idle again)
        
        Partial refreshes also require busy signal checking per UC8151 reference designs.
        """
        from DGTCentaurMods.board.logging import log
        # Step 1: Wait for hardware to be ready
        log.info(f">>> NativeDriver.partial_refresh() waiting for hardware to be idle before sending command (y0={y0}, y1={y1})")
        if not self._wait_for_idle(timeout=5.0):
            raise RuntimeError("Hardware did not become idle before partial_refresh()")
        
        # Step 2: Send partial refresh command
        log.info(f">>> NativeDriver.partial_refresh() sending displayRegion command")
        start_time = time.time()
        self._dll.displayRegion(y0, y1, self._convert(image))
        cmd_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.partial_refresh() displayRegion() returned after {cmd_elapsed:.3f}s")
        
        # Step 3: Wait for hardware to complete refresh
        log.info(f">>> NativeDriver.partial_refresh() waiting for hardware to complete refresh")
        if not self._wait_for_idle(timeout=5.0):
            raise RuntimeError("Hardware did not complete partial refresh within timeout")
        total_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.partial_refresh() complete, total duration={total_elapsed:.3f}s")

    def sleep(self) -> None:
        """
        Put the display into sleep mode.
        
        Per UC8151 reference designs, sleep operations should wait for
        any pending refresh operations to complete before entering sleep.
        """
        from DGTCentaurMods.board.logging import log
        # Wait for hardware to be idle before sleep
        log.info(">>> NativeDriver.sleep() waiting for hardware to be idle before sleep")
        if not self._wait_for_idle(timeout=5.0):
            log.warning("Hardware did not become idle before sleep() - proceeding anyway")
        self._dll.sleepDisplay()

    def shutdown(self) -> None:
        """
        Power off the display.
        
        Per UC8151 reference designs, shutdown operations should wait for
        any pending refresh operations to complete before powering off.
        """
        from DGTCentaurMods.board.logging import log
        # Wait for hardware to be idle before shutdown
        log.info(">>> NativeDriver.shutdown() waiting for hardware to be idle before shutdown")
        if not self._wait_for_idle(timeout=5.0):
            log.warning("Hardware did not become idle before shutdown() - proceeding anyway")
        self._dll.powerOffDisplay()

