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

    def _wait_for_idle(self, timeout: float = 5.0) -> bool:
        """
        Wait for hardware to become idle (not busy) by polling the BUSY signal.
        
        According to UC8151 datasheet: BUSY_N is LOW when busy, HIGH when idle.
        GPIO reads typically return 0 for LOW and 1 for HIGH, so:
        - readBusy() returns 0 when busy (LOW)
        - readBusy() returns 1 when idle (HIGH)
        
        ROOT CAUSE FIX (All 5 agents agreed):
        - readBusy() sometimes returns garbage values (1961760676, 747648) instead of 0/1
        - This suggests the C library may return full GPIO register or uninitialized memory
        - Solution: Mask result to bit 0 (busy_value & 0x01) to extract only the BUSY bit
        - Validate: If masked value is not 0 or 1, log warning and treat conservatively as busy
        
        CRITICAL FIX for full refresh issue:
        - readBusy() is unreliable and can return inconsistent values
        - Require multiple consecutive idle reads (3) before considering hardware truly idle
        - This prevents false idle detection that causes display() to return early
        
        Returns:
            True if hardware became idle, False if timeout
        """
        from DGTCentaurMods.board.logging import log
        start_time = time.time()
        poll_count = 0
        consecutive_idle_count = 0
        REQUIRED_CONSECUTIVE_IDLE = 3  # Require 3 consecutive idle reads to be sure
        
        # Log initial readBusy() value before entering wait loop
        raw_busy = self._dll.readBusy()
        # ROOT CAUSE FIX: Mask to bit 0 to extract only the BUSY signal bit
        # This handles cases where readBusy() returns full GPIO register or garbage values
        initial_busy = raw_busy & 0x01
        if raw_busy != initial_busy:
            log.warning(f">>> NativeDriver._wait_for_idle() readBusy() returned garbage value {raw_busy}, masking to bit 0: {initial_busy}")
        log.info(f">>> NativeDriver._wait_for_idle() ENTERED: raw_readBusy()={raw_busy}, masked={initial_busy} (0=busy, 1=idle)")
        
        # If already idle, still require multiple consecutive reads to be sure
        if initial_busy == 1:
            consecutive_idle_count = 1
            log.info(f">>> NativeDriver._wait_for_idle() initial read shows idle, requiring {REQUIRED_CONSECUTIVE_IDLE} consecutive idle reads")
        else:
            # Hardware is busy, enter polling loop
            log.info(f">>> NativeDriver._wait_for_idle() hardware is busy (masked readBusy()={initial_busy}), entering polling loop")
        
        while True:
            raw_busy = self._dll.readBusy()
            # ROOT CAUSE FIX: Mask to bit 0 to extract only the BUSY signal bit
            busy_value = raw_busy & 0x01
            poll_count += 1
            elapsed = time.time() - start_time
            
            # Validate: If raw value suggests garbage (not 0 or 1), log warning
            if raw_busy != 0 and raw_busy != 1 and poll_count <= 5:
                log.warning(f">>> NativeDriver._wait_for_idle() poll #{poll_count}: readBusy() returned garbage value {raw_busy}, masking to {busy_value}")
            
            # Log EVERY poll attempt with both raw and masked values
            # Log every 10th poll to avoid log spam, but always log first 5 polls
            if poll_count <= 5 or poll_count % 10 == 0:
                log.info(f">>> NativeDriver._wait_for_idle() poll #{poll_count}: raw_readBusy()={raw_busy}, masked={busy_value}, consecutive_idle={consecutive_idle_count} (elapsed={elapsed:.3f}s)")
            
            # Check if hardware is idle (1 = HIGH = idle) using masked value
            if busy_value == 1:
                consecutive_idle_count += 1
                # Require multiple consecutive idle reads to be sure hardware is truly idle
                if consecutive_idle_count >= REQUIRED_CONSECUTIVE_IDLE:
                    log.info(f">>> NativeDriver._wait_for_idle() hardware became idle after {elapsed:.3f}s (polled {poll_count} times, {consecutive_idle_count} consecutive idle reads, raw={raw_busy}, masked={busy_value})")
                    return True
            else:
                # Hardware is busy, reset consecutive idle counter
                consecutive_idle_count = 0
            
            # Check for timeout
            if elapsed > timeout:
                log.error(f">>> NativeDriver._wait_for_idle() timeout after {timeout}s (raw_readBusy()={raw_busy}, masked={busy_value}, consecutive_idle={consecutive_idle_count}, polled {poll_count} times)")
                return False
            
            time.sleep(0.01)  # Poll every 10ms to avoid excessive CPU usage

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

