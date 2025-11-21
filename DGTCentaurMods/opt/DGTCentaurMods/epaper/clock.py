"""
Clock widget displaying current time.
"""

from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from .framework.widget import Widget
import os


class ClockWidget(Widget):
    """24-pixel high clock widget."""
    
    def __init__(self, x: int, y: int):
        super().__init__(x, y, 128, 24)
        self._font = self._load_font()
    
    def _load_font(self):
        """Load font with fallbacks."""
        # font_paths = [
        #     '/opt/DGTCentaurMods/resources/fixed_01.ttf',
        #     'resources/fixed_01.ttf',
        #     '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        # ]
        # for path in font_paths:
        #     if os.path.exists(path):
        #         try:
        #             return ImageFont.truetype(path, 20)
        #         except:
        #             pass
        return ImageFont.load_default()
    
    def render(self) -> Image.Image:
        """Render current time."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")
        draw.text((0, 0), time_str, font=self._font, fill=0)
        return img
