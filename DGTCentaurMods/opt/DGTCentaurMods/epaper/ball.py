"""
Bouncing ball widget for demo purposes.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget


class BallWidget(Widget):
    """Bouncing ball widget for display demos."""
    
    def __init__(self, x: int, y: int, radius: int = 8):
        super().__init__(x, y, radius * 2, radius * 2)
        self.radius = radius
    
    def set_position(self, x: int, y: int) -> None:
        """Set ball position."""
        if self.x != x or self.y != y:
            self.x = x
            self.y = y
            self._last_rendered = None
            self.request_update(full=False)
    
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
