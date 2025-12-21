"""
Pause widget displaying pause icon and PAUSED text.

Shows a pause icon (two vertical bars) and "PAUSED" text when game is paused.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
from .text import TextWidget, Justify


class PauseWidget(Widget):
    """Widget showing pause icon and PAUSED text.
    
    Displays centered on the screen with:
    - Two vertical bars (pause icon) at top
    - "PAUSED" text below
    """
    
    def __init__(self, x: int = 0, y: int = 98, width: int = 128, height: int = 100,
                 update_callback=None):
        """Initialize the pause widget.
        
        Args:
            x: X position on display (default 0)
            y: Y position on display (default 98, centered on 296px display)
            width: Widget width (default 128)
            height: Widget height (default 100)
            update_callback: Callback to trigger display updates
        """
        super().__init__(x=x, y=y, width=width, height=height, update_callback=update_callback)
        self._text_widget = TextWidget(
            x=0, y=60, width=width, height=30, update_callback=update_callback,
            text="PAUSED", font_size=24,
            justify=Justify.CENTER, transparent=True
        )
    
    def draw_on(self, img: Image.Image, draw_x: int, draw_y: int) -> None:
        """Draw the pause widget onto the target image.
        
        Args:
            img: Target PIL Image to draw on
            draw_x: X coordinate to draw at
            draw_y: Y coordinate to draw at
        """
        # Draw background first
        self.draw_background(img, draw_x, draw_y)
        
        draw = ImageDraw.Draw(img)
        
        # Draw pause icon (two vertical bars) centered at top
        bar_width = 12
        bar_height = 50
        gap = 16
        total_width = bar_width * 2 + gap
        start_x = draw_x + (self.width - total_width) // 2
        start_y = draw_y + 5
        
        # Left bar
        draw.rectangle([start_x, start_y, start_x + bar_width, start_y + bar_height], fill=0)
        # Right bar
        draw.rectangle([start_x + bar_width + gap, start_y, 
                       start_x + bar_width * 2 + gap, start_y + bar_height], fill=0)
        
        # Draw "PAUSED" text below
        self._text_widget.draw_on(img, draw_x, draw_y + 60)
