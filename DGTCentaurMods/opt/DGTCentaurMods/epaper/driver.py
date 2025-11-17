"""
Hardware driver wrapper for the Waveshare e-Paper Python library.

This driver extends Waveshare's EPD class with true partial update support
and provides a clean interface for the widget framework.
"""

from __future__ import annotations

from PIL import Image

from .waveshare_epd2in9d import EPD as WaveshareEPD


class Driver:
    """
    Wraps and extends the Waveshare e-Paper Python library.
    
    Provides true partial update support using UC8151 controller commands.
    """

    def __init__(self) -> None:
        self._epd = WaveshareEPD()
        
        # Display dimensions (vertical orientation: width=128, height=296)
        self.width = 128
        self.height = 296
        
        # Track initialization state
        self._initialized = False

    def init(self) -> None:
        """Initialize the display hardware."""
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

    def clear(self) -> None:
        """Clear the entire display to white."""
        if not self._initialized:
            self.init()
        self._epd.Clear()

    def full_refresh(self, image: Image.Image) -> None:
        """
        Perform a full screen refresh.
        
        Args:
            image: PIL Image in vertical orientation (width=128, height=296)
        """
        if not self._initialized:
            self.init()
        
        # Ensure image is correct size and mode
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height), Image.Resampling.LANCZOS)
        
        if image.mode != "1":
            image = image.convert("1")
        
        # Rotate 180 degrees to match hardware orientation
        rotated = image.transpose(Image.ROTATE_180)
        
        # Convert to buffer using Waveshare's getbuffer
        buf = self._epd.getbuffer(rotated)
        
        # Use Waveshare's display method
        self._epd.display(buf)

    def partial_refresh(self, x1: int, y1: int, x2: int, y2: int, image: Image.Image) -> None:
        """
        Perform a true partial screen refresh for a specific region.
        
        Args:
            x1: Start x coordinate (inclusive, pixels) in framework coordinates
            y1: Start y coordinate (inclusive, pixels) in framework coordinates
            x2: End x coordinate (exclusive, pixels) in framework coordinates
            y2: End y coordinate (exclusive, pixels) in framework coordinates
            image: PIL Image of the FULL SCREEN (width=128, height=296)
        
        Only the specified region will be refreshed. X coordinates are aligned
        to byte boundaries (8 pixels) automatically.
        """
        if not self._initialized:
            self.init()
        
        # Ensure we have a full-screen image
        if image.size != (self.width, self.height):
            # If a region was passed, create full-screen and paste it
            full_image = Image.new("1", (self.width, self.height), 255)
            full_image.paste(image, (x1, y1))
            image = full_image
        
        # Ensure 1-bit mode
        if image.mode != "1":
            image = image.convert("1")
        
        # Rotate 180 degrees to match hardware orientation
        rotated = image.transpose(Image.ROTATE_180)
        
        # Convert to buffer using Waveshare's getbuffer
        # The buffer is now in hardware coordinate system (rotated)
        buf = self._epd.getbuffer(rotated)
        
        # Convert framework coordinates to hardware coordinates (rotated 180°)
        # Framework: (0,0) top-left, (width, height) bottom-right
        # Hardware: (0,0) bottom-right (after rotation), (width, height) top-left
        # After rotation: point (x, y) in framework becomes (width-x, height-y) in hardware
        hw_x1 = self.width - x2
        hw_y1 = self.height - y2
        hw_x2 = self.width - x1
        hw_y2 = self.height - y1
        
        # Ensure coordinates are valid
        hw_x1 = max(0, min(hw_x1, self.width))
        hw_y1 = max(0, min(hw_y1, self.height))
        hw_x2 = max(0, min(hw_x2, self.width))
        hw_y2 = max(0, min(hw_y2, self.height))
        
        # Ensure x1 < x2 and y1 < y2
        if hw_x1 >= hw_x2 or hw_y1 >= hw_y2:
            return
        
        # Use true partial refresh with hardware coordinates
        # The buffer is already in hardware coordinates, so we extract using hw coords
        self._epd.DisplayPartialRegion(buf, hw_x1, hw_y1, hw_x2, hw_y2)

    def sleep(self) -> None:
        """Put the display into sleep mode."""
        if self._initialized:
            self._epd.sleep()
            self._initialized = False

    def shutdown(self) -> None:
        """Power off the display."""
        if self._initialized:
            self.sleep()
