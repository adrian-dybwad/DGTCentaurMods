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
    
    This replaces the compiled epaperDriver.so with a pure Python implementation.
    """

    def __init__(self) -> None:
        self._epd = WaveshareEPD()
        
        # Display dimensions (vertical orientation: width=128, height=296)
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
            try:
                result = self._epd.init()
                if result != 0:
                    raise RuntimeError(f"Failed to initialize e-Paper display (return code: {result})")
                self._initialized = True
            except Exception as e:
                raise RuntimeError(f"Failed to initialize e-Paper display: {e}") from e

    def reset(self) -> None:
        """Reset the display hardware."""
        self._epd.reset()

    def full_refresh(self, image: Image.Image) -> None:
        """
        Perform a full screen refresh.
        
        Args:
            image: PIL Image in vertical orientation (width=128, height=296)
        
        The refresh blocks until the hardware operation completes.
        Typical duration is 1.5-2.0 seconds.
        """
        if not self._initialized:
            self.init()
        
        # Ensure image is correct size and mode
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height), Image.Resampling.LANCZOS)
        
        if image.mode != "1":
            image = image.convert("1")
        
        # Convert to buffer format - getbuffer handles orientation automatically
        # It expects vertical orientation (128x296) and processes it directly
        buf = self._epd.getbuffer(image)
        
        # Perform full refresh
        self._epd.display(buf)

    def partial_refresh(self, x1: int, y1: int, x2: int, y2: int, image: Image.Image) -> None:
        """
        Perform a partial screen refresh.
        
        Args:
            x1, y1, x2, y2: Coordinates (for reference only, DisplayPartial always does full screen)
            image: PIL Image of the FULL SCREEN (width=128, height=296)
        
        Note: Waveshare DisplayPartial always refreshes the full screen.
        The "partial" refers to the refresh waveform (faster, less ghosting),
        not the region size. The image parameter must be full-screen.
        """
        if not self._initialized:
            self.init()
        
        # Ensure we have a full-screen image
        if image.size != (self.width, self.height):
            # If a region was passed, create full-screen and paste it
            full_image = Image.new("1", (self.width, self.height), 255)  # White background
            full_image.paste(image, (x1, y1))
            image = full_image
        
        # Ensure 1-bit mode
        if image.mode != "1":
            image = image.convert("1")
        
        # Convert to buffer format - getbuffer handles orientation automatically
        buf = self._epd.getbuffer(image)
        
        # Use Waveshare DisplayPartial - this always refreshes full screen
        # but uses a faster partial refresh waveform
        self._epd.DisplayPartial(buf)

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
