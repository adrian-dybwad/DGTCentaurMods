"""
Hardware driver wrapper for the Waveshare e-Paper Python library.
"""

from __future__ import annotations

from PIL import Image

# Import Waveshare driver components
from .waveshare_epd2in9d import EPD as WaveshareEPD
from . import waveshare_epdconfig as epdconfig


class Driver:
    """
    Wraps the Waveshare e-Paper Python library.
    
    This replaces the compiled epaperDriver.so with a pure Python implementation
    that supports partial refreshes with x/y coordinates.
    """

    def __init__(self) -> None:
        self._epd = WaveshareEPD()
        
        # Display dimensions
        self.width = 128
        self.height = 296
        
        # Track initialization state
        self._initialized = False

    def init(self) -> None:
        """
        Initialize the display hardware.
        
        This must be called before any display operations.
        """
        if not self._initialized:
            result = self._epd.init()
            if result != 0:
                raise RuntimeError("Failed to initialize e-Paper display")
            self._initialized = True

    def reset(self) -> None:
        """
        Reset the display hardware.
        """
        self._epd.reset()

    def full_refresh(self, image: Image.Image) -> None:
        """
        Perform a full screen refresh.
        
        Args:
            image: PIL Image to display (will be rotated to match hardware orientation)
        
        The refresh blocks until the hardware operation completes.
        Typical duration is 1.5-2.0 seconds based on UC8151 controller specifications.
        """
        if not self._initialized:
            self.init()
        
        # Rotate 180 degrees to match hardware orientation
        rotated = image.transpose(Image.ROTATE_180)
        
        # Convert to buffer format expected by Waveshare driver
        buf = self._epd.getbuffer(rotated)
        
        # Perform full refresh
        self._epd.display(buf)

    def partial_refresh(self, x1: int, y1: int, x2: int, y2: int, image: Image.Image) -> None:
        """
        Perform a partial screen refresh with x/y coordinates.
        
        Args:
            x1: Start x coordinate (inclusive)
            y1: Start y coordinate (inclusive)
            x2: End x coordinate (exclusive)
            y2: End y coordinate (exclusive)
            image: PIL Image to display (will be rotated to match hardware orientation)
        
        The refresh blocks until the hardware operation completes.
        Typical duration is 260-300ms based on UC8151 controller specifications.
        
        Note: Coordinates are in the framework's coordinate system (top-left origin).
        The image will be rotated to match hardware orientation.
        """
        if not self._initialized:
            self.init()
        
        # Rotate 180 degrees to match hardware orientation
        rotated = image.transpose(Image.ROTATE_180)
        
        # Convert to buffer format (full screen buffer)
        buf = self._epd.getbuffer(rotated)
        
        # Set up partial refresh mode
        self._epd.SetPartReg()
        
        # Set partial window with x/y coordinates
        # Command 0x91: Enter partial mode
        self._epd.send_command(0x91)
        
        # Command 0x90: Set partial window
        self._epd.send_command(0x90)
        
        # Convert coordinates to hardware orientation (rotated 180 degrees)
        # In hardware coordinates (from bottom-left), we need to invert
        hw_x1 = self.width - x2
        hw_x2 = self.width - x1 - 1
        hw_y1 = self.height - y2
        hw_y2 = self.height - y1 - 1
        
        # Clamp to display bounds
        hw_x1 = max(0, min(hw_x1, self.width - 1))
        hw_x2 = max(0, min(hw_x2, self.width - 1))
        hw_y1 = max(0, min(hw_y1, self.height - 1))
        hw_y2 = max(0, min(hw_y2, self.height - 1))
        
        # Send partial window coordinates
        # Format: x_start, x_end, y_start (2 bytes), y_end (2 bytes), rotation
        self._epd.send_data(hw_x1)
        self._epd.send_data(hw_x2)
        self._epd.send_data(int(hw_y1 / 256))
        self._epd.send_data(hw_y1 % 256)
        self._epd.send_data(int(hw_y2 / 256))
        self._epd.send_data(hw_y2 % 256)
        self._epd.send_data(0x28)  # Rotation
        
        # For partial refresh, we still send the full buffer
        # but only the partial window region will be updated
        # Create inverted buffer for old data (white background)
        buf_inverted = [0x00] * len(buf)
        for i in range(len(buf)):
            buf_inverted[i] = ~buf[i] & 0xFF
        
        # Send old data (white background) - full buffer
        self._epd.send_command(0x10)
        self._epd.send_data2(buf)
        epdconfig.delay_ms(10)
        
        # Send new data - full buffer (only partial window will update)
        self._epd.send_command(0x13)
        self._epd.send_data2(buf_inverted)
        epdconfig.delay_ms(10)
        
        # Turn on display to execute refresh
        self._epd.TurnOnDisplay()

    def sleep(self) -> None:
        """Put the display into sleep mode."""
        if self._initialized:
            self._epd.sleep()
            self._initialized = False

    def shutdown(self) -> None:
        """Power off the display."""
        if self._initialized:
            self.sleep()
            # epdconfig.module_exit() is called by sleep()
