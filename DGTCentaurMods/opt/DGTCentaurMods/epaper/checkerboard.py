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
    """Checkerboard widget that renders a checkerboard pattern with configurable square size."""
    
    def __init__(self, x: int, y: int, width: int, height: int, update_callback, square_size: int = 64):
        super().__init__(x, y, width, height, update_callback)
        self._square_size = square_size
    
    def render(self, sprite: Image.Image) -> None:
        """Render checkerboard pattern onto the sprite image."""
        draw = ImageDraw.Draw(sprite)
        
        # Calculate number of squares
        squares_x = self.width // self._square_size
        squares_y = self.height // self._square_size
        
        log.debug(f"CheckerboardWidget.render(): Rendering {squares_x}x{squares_y} squares (size={self._square_size}px, widget={self.width}x{self.height})")
        
        # Draw checkerboard pattern
        squares_drawn = 0
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
                squares_drawn += 1
        
        log.debug(f"CheckerboardWidget.render(): Drew {squares_drawn} squares")

