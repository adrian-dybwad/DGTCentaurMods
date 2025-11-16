"""
Text widget for displaying static or dynamic text.
"""

from PIL import Image, ImageDraw, ImageFont

from ..widget import Widget


class TextWidget(Widget):
    """
    Widget that displays text.
    
    Text can be updated by calling set_text().
    """

    def __init__(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        font_size: int = 18,
        text: str = ""
    ) -> None:
        """
        Initialize text widget.
        
        Args:
            x: X position
            y: Y position
            width: Widget width
            height: Widget height
            font_size: Font size (default 18)
            text: Initial text (default empty)
        """
        super().__init__(x, y, width, height)
        self.font_size = font_size
        self._text = text
        self._font: ImageFont.FreeTypeFont | None = None

    def set_text(self, text: str) -> None:
        """
        Set the text to display.
        
        Args:
            text: Text to display
        """
        self._text = text

    def _get_font(self) -> ImageFont.FreeTypeFont:
        """Get or create the font."""
        if self._font is None:
            import os
            # Try project font first
            font_paths = [
                "/opt/DGTCentaurMods/resources/Font.ttc",
                "/home/pi/resources/Font.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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
        """Render the text."""
        image = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(image)
        
        font = self._get_font()
        
        # Draw text (clip to widget bounds)
        draw.text((0, 0), self._text, font=font, fill=0)
        
        return image

