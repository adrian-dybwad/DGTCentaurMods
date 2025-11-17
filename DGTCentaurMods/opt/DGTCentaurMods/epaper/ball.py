"""
Bouncing ball widget.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
from .framework.regions import Region


class BallWidget(Widget):
    """Bouncing ball widget."""
    
    def __init__(self, x: int, y: int, radius: int = 8):
        super().__init__(x, y, radius * 2, radius * 2)
        self.radius = radius
        self._prev_x = x
        self._prev_y = y
    
    def set_position(self, x: int, y: int) -> None:
        """Set ball position."""
        self._prev_x = self.x
        self._prev_y = self.y
        self.x = x
        self.y = y
        self._last_rendered = None
    
    def get_previous_region(self) -> Region:
        """Get the previous position region for clearing."""
        return Region(self._prev_x, self._prev_y, 
                     self._prev_x + self.width, self._prev_y + self.height)
    
    def get_mask(self) -> Image.Image:
        """Get mask for transparent compositing."""
        mask = Image.new("1", (self.width, self.height), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse([0, 0, self.width - 1, self.height - 1], fill=255)
        return mask
    
    def render(self) -> Image.Image:
        """Render ball."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        draw.ellipse([0, 0, self.width - 1, self.height - 1], fill=0)
        return img
