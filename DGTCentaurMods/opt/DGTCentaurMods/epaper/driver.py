"""
Hardware driver wrapper for the native epaperDriver.so library.
"""

from __future__ import annotations

import pathlib
from ctypes import CDLL, c_int

from PIL import Image


class Driver:
    """
    Wraps the native epaperDriver.so shared library.
    
    The shared object handles SPI communication with the UC8151 controller.
    """

    def __init__(self) -> None:
        # Locate epaperDriver.so in the same directory
        lib_path = pathlib.Path(__file__).resolve().parent / "epaperDriver.so"
        if not lib_path.exists():
            raise FileNotFoundError(f"Native ePaper driver not found at {lib_path}")
        
        self._dll = CDLL(str(lib_path))
        self._dll.openDisplay()
        
        # Configure readBusy function signature
        self._dll.readBusy.argtypes = []
        self._dll.readBusy.restype = c_int
        
        # Display dimensions
        self.width = 128
        self.height = 296

    def _convert_to_bytes(self, image: Image.Image) -> bytes:
        """
        Convert PIL Image to byte buffer format expected by driver.
        
        The driver expects a 1-bit monochrome bitmap in row-major order,
        with each byte containing 8 pixels (MSB first).
        """
        width, height = image.size
        buf = [0xFF] * (int(width / 8) * height)
        mono = image.convert("1")
        pixels = mono.load()
        
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == 0:  # Black pixel
                    byte_index = int((x + y * width) / 8)
                    bit_position = x % 8
                    buf[byte_index] &= ~(0x80 >> bit_position)
        
        return bytes(buf)

    def init(self) -> None:
        """
        Initialize the display hardware.
        
        The C library handles all timing internally.
        """
        self._dll.init()

    def reset(self) -> None:
        """
        Reset the display hardware.
        
        The C library handles all timing internally.
        """
        self._dll.reset()

    def full_refresh(self, image: Image.Image) -> None:
        """
        Perform a full screen refresh.
        
        The C library's display() function blocks until the hardware
        refresh completes (typically 1.5-2.0 seconds).
        """
        # Rotate 180 degrees to match hardware orientation
        rotated = image.transpose(Image.ROTATE_180)
        self._dll.display(self._convert_to_bytes(rotated))

    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        """
        Perform a partial screen refresh.
        
        Args:
            y0: Start row (in hardware coordinates, from bottom)
            y1: End row (in hardware coordinates, from bottom)
            image: Image to display (will be rotated and cropped)
        
        The C library's displayRegion() function blocks until the hardware
        refresh completes (typically 260-300ms).
        """
        # Rotate 180 degrees to match hardware orientation
        rotated = image.transpose(Image.ROTATE_180)
        self._dll.displayRegion(y0, y1, self._convert_to_bytes(rotated))

    def sleep(self) -> None:
        """Put the display into sleep mode."""
        self._dll.sleepDisplay()

    def shutdown(self) -> None:
        """Power off the display."""
        self._dll.powerOffDisplay()

