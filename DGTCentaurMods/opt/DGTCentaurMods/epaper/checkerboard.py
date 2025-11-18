"""
Checkerboard widget displaying an 8x8 pixel checkerboard pattern.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class CheckerboardWidget(Widget):
    """Checkerboard widget that renders an 8x8 pixel checkerboard pattern."""
    
    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self._square_size = 8  # 8x8 pixel squares
    
    def render(self) -> Image.Image:
        """Render checkerboard pattern."""
        img = Image.new("1", (self.width, self.height), 255)  # White background
        draw = ImageDraw.Draw(img)
        
        # Calculate number of squares
        squares_x = self.width // self._square_size
        squares_y = self.height // self._square_size
        
        # Draw checkerboard pattern
        for row in range(squares_y):
            for col in range(squares_x):
                # Alternate colors: black if (row + col) is odd
                is_black = (row + col) % 2 == 1
                
                x1 = col * self._square_size
                y1 = row * self._square_size
                x2 = x1 + self._square_size
                y2 = y1 + self._square_size
                
                fill_color = 0 if is_black else 255
                draw.rectangle([(x1, y1), (x2, y2)], fill=fill_color)
        
        return img

