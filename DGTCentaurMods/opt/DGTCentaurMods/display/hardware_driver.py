"""
Hardware driver for e-paper display (wrapper around C library).

This file is part of the DGTCentaur Mods open source software
( https://github.com/EdNekebno/DGTCentaur )

DGTCentaur Mods is free software: you can redistribute
it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version.

DGTCentaur Mods is distributed in the hope that it will
be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this file.  If not, see

https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md

This and any other notices must remain intact and unaltered in any
distribution, modification, variant, or derivative of this software.
"""

from ctypes import CDLL
from pathlib import Path
from typing import Optional
from PIL import Image

from DGTCentaurMods.display.display_types import DISPLAY_WIDTH, DISPLAY_HEIGHT


class HardwareDriver:
    """
    Hardware driver for e-paper display.
    
    Wraps the C library (epaperDriver.so) providing a clean Python interface.
    Implements singleton pattern to ensure only one instance exists.
    """
    
    _instance: Optional['HardwareDriver'] = None
    _driver_func: Optional[CDLL] = None
    
    def __new__(cls):
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super(HardwareDriver, cls).__new__(cls)
            cls._initialize_driver()
        return cls._instance
    
    @classmethod
    def _initialize_driver(cls) -> None:
        """Load and initialize the C driver library."""
        driver_path = Path(__file__).parent / "epaperDriver.so"
        cls._driver_func = CDLL(str(driver_path))
        cls._driver_func.openDisplay()
    
    def _image_to_buffer(self, image: Image.Image) -> bytes:
        """
        Convert a PIL Image to a byte buffer for the hardware.
        
        Supports vertical (128x296) and horizontal (296x128) orientations.
        
        Args:
            image: PIL Image in mode '1' (1-bit)
            
        Returns:
            Bytes buffer for display hardware
        """
        buf = [0xFF] * (int(DISPLAY_WIDTH / 8) * DISPLAY_HEIGHT)
        image_mono = image.convert('1')
        width, height = image_mono.size
        pixels = image_mono.load()
        
        if width == DISPLAY_WIDTH and height == DISPLAY_HEIGHT:
            # Vertical orientation (normal)
            for y in range(height):
                for x in range(width):
                    if pixels[x, y] == 0:
                        buf[int((x + y * DISPLAY_WIDTH) / 8)] &= ~(0x80 >> (x % 8))
        
        elif width == DISPLAY_HEIGHT and height == DISPLAY_WIDTH:
            # Horizontal orientation (rotated)
            for y in range(height):
                for x in range(width):
                    new_x = y
                    new_y = DISPLAY_HEIGHT - x - 1
                    if pixels[x, y] == 0:
                        buf[int((new_x + new_y * DISPLAY_WIDTH) / 8)] &= ~(0x80 >> (y % 8))
        
        else:
            # Other sizes - attempt to display as-is
            for y in range(min(height, DISPLAY_HEIGHT)):
                for x in range(min(width, DISPLAY_WIDTH)):
                    if pixels[x, y] == 0:
                        buf[int((x + y * DISPLAY_WIDTH) / 8)] &= ~(0x80 >> (x % 8))
        
        return bytes(buf)
    
    def init(self) -> None:
        """Initialize the display hardware."""
        if self._driver_func:
            self._driver_func.init()
    
    def reset(self) -> None:
        """Reset the display hardware."""
        if self._driver_func:
            self._driver_func.reset()
    
    def clear(self) -> None:
        """Clear the display to white."""
        if self._driver_func:
            self._driver_func.clear()
    
    def display(self, image: Image.Image) -> None:
        """
        Display a full screen image.
        
        Args:
            image: PIL Image to display
        """
        if self._driver_func:
            buffer = self._image_to_buffer(image)
            self._driver_func.display(buffer)
    
    def display_partial(self, image: Image.Image) -> None:
        """
        Display a full screen image using partial refresh.
        
        Partial refresh is faster but may have ghosting.
        
        Args:
            image: PIL Image to display
        """
        if self._driver_func:
            buffer = self._image_to_buffer(image)
            self._driver_func.displayPartial(buffer)
    
    def display_region(self, y0: int, y1: int, image: Image.Image) -> None:
        """
        Display a partial region of the screen.
        
        Most efficient update method for small changes.
        
        Args:
            y0: Start row (0-295)
            y1: End row (0-295)
            image: PIL Image to display in the region
        """
        if self._driver_func:
            buffer = self._image_to_buffer(image)
            self._driver_func.displayRegion(y0, y1, buffer)
    
    def sleep_display(self) -> None:
        """Put the display into low-power sleep mode."""
        if self._driver_func:
            self._driver_func.sleepDisplay()
    
    def power_off_display(self) -> None:
        """Power off the display completely."""
        if self._driver_func:
            self._driver_func.powerOffDisplay()
    
    def get_buffer(self, image: Image.Image) -> bytes:
        """
        Get the byte buffer representation of an image.
        
        Useful for comparing images without sending to display.
        
        Args:
            image: PIL Image
            
        Returns:
            Bytes buffer
        """
        return self._image_to_buffer(image)

