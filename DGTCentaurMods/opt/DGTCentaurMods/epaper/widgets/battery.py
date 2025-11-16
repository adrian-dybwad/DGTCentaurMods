"""
Battery level widget.
"""

from PIL import Image, ImageDraw

from ..widget import Widget


class BatteryWidget(Widget):
    """
    Widget that displays battery level as a simple bar.
    
    Shows battery level from 0-100% as a filled rectangle.
    """

    def __init__(self, x: int, y: int, width: int = 30, height: int = 12) -> None:
        """
        Initialize battery widget.
        
        Args:
            x: X position
            y: Y position
            width: Widget width (default 30)
            height: Widget height (default 12)
        """
        super().__init__(x, y, width, height)
        self._level = 100

    def set_level(self, level: int) -> None:
        """
        Set battery level.
        
        Args:
            level: Battery level 0-100
        """
        self._level = max(0, min(100, level))

    def render(self) -> Image.Image:
        """Render the battery level."""
        image = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(image)
        
        # Draw border
        draw.rectangle(
            (0, 0, self.width - 1, self.height - 1),
            fill=255,
            outline=0,
            width=1
        )
        
        # Draw battery tip (right side)
        tip_width = 2
        tip_height = 4
        tip_x = self.width - tip_width
        tip_y = (self.height - tip_height) // 2
        draw.rectangle(
            (tip_x, tip_y, tip_x + tip_width, tip_y + tip_height),
            fill=0,
            outline=0
        )
        
        # Draw filled portion based on level
        if self._level > 0:
            fill_width = int((self.width - tip_width - 2) * self._level / 100)
            if fill_width > 0:
                draw.rectangle(
                    (1, 1, 1 + fill_width, self.height - 2),
                    fill=0,
                    outline=0
                )
        
        return image

