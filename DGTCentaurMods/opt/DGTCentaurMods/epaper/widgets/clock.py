"""
Clock widget that displays current time.
"""

import time
from PIL import Image, ImageDraw, ImageFont

from ..widget import Widget


class ClockWidget(Widget):
    """
    Widget that displays the current time in HH:MM format.
    
    Updates automatically when render() is called with a new time.
    """

    def __init__(self, x: int, y: int, height: int = 24, font_size: int = 20) -> None:
        """
        Initialize clock widget.
        
        Args:
            x: X position
            y: Y position
            height: Widget height in pixels (default 24)
            font_size: Font size for time display (default 20)
        """
        # Calculate width based on font (HH:MM format is ~60 pixels at size 20)
        width = 80
        super().__init__(x, y, width, height)
        self.font_size = font_size
        self._font: ImageFont.FreeTypeFont | None = None

    def _get_font(self) -> ImageFont.FreeTypeFont:
        """Get or create the font."""
        if self._font is None:
            import os
            # Try project font first
            font_paths = [
                "/opt/DGTCentaurMods/resources/Font.ttc",
                "/home/pi/resources/Font.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
            for font_path in font_paths:
                if os.path.exists(font_path):
                    try:
                        self._font = ImageFont.truetype(font_path, self.font_size)
                        break
                    except (OSError, IOError):
                        continue
            # Fallback to default font
            if self._font is None:
                self._font = ImageFont.load_default()
        return self._font

    def render(self) -> Image.Image:
        """Render the current time."""
        image = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(image)
        
        # Get current time
        current_time = time.strftime("%H:%M")
        
        # Draw time text
        font = self._get_font()
        draw.text((0, 0), current_time, font=font, fill=0)
        
        return image

