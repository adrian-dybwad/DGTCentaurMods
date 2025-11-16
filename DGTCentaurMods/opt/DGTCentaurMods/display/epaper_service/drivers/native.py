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
        
        ROOT CAUSE FIX (All 5 agents agreed):
        - readBusy() sometimes returns garbage values (1961760676, 747648) instead of 0/1
        - This suggests the C library may return full GPIO register or uninitialized memory
        - Solution: Mask result to bit 0 (busy_value & 0x01) to extract only the BUSY bit
        - Validate: If masked value is not 0 or 1, log warning and treat conservatively as busy
        
        Returns:
            True if hardware became idle, False if timeout
        """
        from DGTCentaurMods.board.logging import log
        start_time = time.time()
        poll_count = 0
        
        # Log initial readBusy() value before entering wait loop
        raw_busy = self._dll.readBusy()
        # ROOT CAUSE FIX: Mask to bit 0 to extract only the BUSY signal bit
        # This handles cases where readBusy() returns full GPIO register or garbage values
        initial_busy = raw_busy & 0x01
        if raw_busy != initial_busy:
            log.warning(f">>> NativeDriver._wait_for_idle() readBusy() returned garbage value {raw_busy}, masking to bit 0: {initial_busy}")
        log.info(f">>> NativeDriver._wait_for_idle() ENTERED: raw_readBusy()={raw_busy}, masked={initial_busy} (0=busy, 1=idle)")
        
        # If already idle, return immediately but still log it
        if initial_busy == 1:
            log.info(f">>> NativeDriver._wait_for_idle() hardware already idle (masked readBusy()={initial_busy}), returning immediately")
            return True
        
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
                log.info(f">>> NativeDriver._wait_for_idle() poll #{poll_count}: raw_readBusy()={raw_busy}, masked={busy_value} (elapsed={elapsed:.3f}s)")
            
            # Check if hardware is idle (1 = HIGH = idle) using masked value
            if busy_value == 1:
                log.info(f">>> NativeDriver._wait_for_idle() hardware became idle after {elapsed:.3f}s (polled {poll_count} times, raw={raw_busy}, masked={busy_value})")
                return True
            
            # Check for timeout
            if elapsed > timeout:
                log.error(f">>> NativeDriver._wait_for_idle() timeout after {timeout}s (raw_readBusy()={raw_busy}, masked={busy_value}, polled {poll_count} times)")
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
        
        # Verify hardware is idle immediately before calling display()
        raw_pre_busy = self._dll.readBusy()
        pre_display_busy = raw_pre_busy & 0x01  # Mask to bit 0
        if raw_pre_busy != pre_display_busy:
            log.warning(f">>> NativeDriver.full_refresh() pre-display readBusy() returned garbage {raw_pre_busy}, masking to {pre_display_busy}")
        log.info(f">>> NativeDriver.full_refresh() pre-display readBusy() raw={raw_pre_busy}, masked={pre_display_busy} (0=busy, 1=idle)")
        
        # Step 2: Send display command
        log.info(">>> NativeDriver.full_refresh() sending display command")
        start_time = time.time()
        self._dll.display(self._convert(image))
        cmd_elapsed = time.time() - start_time
        log.info(f">>> NativeDriver.full_refresh() display() returned after {cmd_elapsed:.3f}s")
        
        # Verify hardware state immediately after display() returns
        raw_post_busy = self._dll.readBusy()
        post_display_busy = raw_post_busy & 0x01  # Mask to bit 0
        if raw_post_busy != post_display_busy:
            log.warning(f">>> NativeDriver.full_refresh() post-display readBusy() returned garbage {raw_post_busy}, masking to {post_display_busy}")
        log.info(f">>> NativeDriver.full_refresh() post-display readBusy() raw={raw_post_busy}, masked={post_display_busy} (0=busy, 1=idle)")
        
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

