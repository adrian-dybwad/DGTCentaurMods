"""
Battery level indicator widget.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget


class BatteryWidget(Widget):
    """Battery level indicator."""
    
    def __init__(self, x: int, y: int, level: int = 75):
        super().__init__(x, y, 32, 16)
        self.level = level
    
    def set_level(self, level: int) -> None:
        """Set battery level (0-100)."""
        self.level = max(0, min(100, level))
    
    def render(self) -> Image.Image:
        """Render battery indicator."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Battery outline
        draw.rectangle([2, 4, 26, 12], outline=0, width=1)
        draw.rectangle([26, 6, 28, 10], fill=0)
        
        # Battery level
        fill_width = int((self.level / 100) * 22)
        if fill_width > 0:
            draw.rectangle([3, 5, 3 + fill_width, 11], fill=0)
        
        return img
