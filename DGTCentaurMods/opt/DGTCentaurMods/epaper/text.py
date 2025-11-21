"""
Text display widget.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
import os


class TextWidget(Widget):
    """Text display widget."""
    
    def __init__(self, x: int, y: int, width: int, height: int, text: str = ""):
        super().__init__(x, y, width, height)
        self.text = text
        self._font = self._load_font()
    
    def _load_font(self):
        """Load font with fallbacks."""
        font_paths = [
            '/opt/DGTCentaurMods/resources/fixed_01.ttf',
            'resources/fixed_01.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, 12)
                except:
                    pass
        return ImageFont.load_default()
    
    def set_text(self, text: str) -> None:
        """Set the text to display."""
        if self.text != text:
            self.text = text
            self._last_rendered = None
            self.request_update(full=False)
    
    def render(self) -> Image.Image:
        """Render text."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), self.text, font=self._font, fill=0)
        return img
