"""
Brain hint widget displaying the suggested piece type for Hand+Brain mode.

Shows a large single letter indicating which piece type the "brain" (engine)
suggests moving. Used in Hand+Brain chess variant where the engine picks
the piece type and the human picks the specific move.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
import os


class BrainHintWidget(Widget):
    """Widget displaying the brain's suggested piece type.
    
    Shows a large letter (K, Q, R, B, N, P) indicating which piece type
    the engine recommends moving. The player must then choose which
    specific piece of that type to move and where.
    """
    
    def __init__(self, x: int, y: int, width: int = 128, height: int = 72):
        """Initialize the brain hint widget.
        
        Args:
            x: X position on display
            y: Y position on display
            width: Widget width (default 128 - full display width)
            height: Widget height (default 72 - space below analysis widget)
        """
        super().__init__(x, y, width, height)
        self._piece_letter = ""  # Empty = no hint shown
        self._font_large = self._load_font(48)
        self._font_small = self._load_font(12)
    
    def _load_font(self, size: int):
        """Load font with fallbacks.
        
        Args:
            size: Font size in points
            
        Returns:
            PIL ImageFont object
        """
        font_paths = [
            '/opt/DGTCentaurMods/resources/Font.ttc',
            'resources/Font.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()
    
    def set_piece(self, piece_symbol: str) -> None:
        """Set the piece type to display.
        
        Args:
            piece_symbol: Single letter piece symbol (K, Q, R, B, N, P) or
                         empty string to clear the hint.
        """
        # Normalize to uppercase
        new_letter = piece_symbol.upper() if piece_symbol else ""
        
        if new_letter != self._piece_letter:
            self._piece_letter = new_letter
            self._last_rendered = None
            self.request_update(full=False)
    
    def clear(self) -> None:
        """Clear the hint display."""
        self.set_piece("")
    
    def render(self) -> Image.Image:
        """Render the brain hint widget.
        
        Returns:
            PIL Image with the rendered widget
        """
        # Return cached image if available
        if self._last_rendered is not None:
            return self._last_rendered
        
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        if self._piece_letter:
            # Draw "BRAIN:" label at top
            label = "BRAIN:"
            label_bbox = draw.textbbox((0, 0), label, font=self._font_small)
            label_width = label_bbox[2] - label_bbox[0]
            label_x = (self.width - label_width) // 2
            draw.text((label_x, 2), label, font=self._font_small, fill=0)
            
            # Draw large piece letter centered
            letter_bbox = draw.textbbox((0, 0), self._piece_letter, font=self._font_large)
            letter_width = letter_bbox[2] - letter_bbox[0]
            letter_height = letter_bbox[3] - letter_bbox[1]
            letter_x = (self.width - letter_width) // 2
            letter_y = 16 + (self.height - 16 - letter_height) // 2
            draw.text((letter_x, letter_y), self._piece_letter, font=self._font_large, fill=0)
        
        # Cache the rendered image
        self._last_rendered = img
        return img
