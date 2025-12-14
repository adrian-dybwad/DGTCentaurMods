"""
Brain hint widget displaying the suggested piece type for Hand+Brain mode.

Shows a large single letter indicating which piece type the "brain" (engine)
suggests moving. Used in Hand+Brain chess variant where the engine picks
the piece type and the human picks the specific move.

Uses TextWidget for all text rendering.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
from .text import TextWidget, Justify


class BrainHintWidget(Widget):
    """Widget displaying the brain's suggested piece type.
    
    Shows a large letter (K, Q, R, B, N, P) indicating which piece type
    the engine recommends moving. The player must then choose which
    specific piece of that type to move and where.
    
    Uses TextWidget for text rendering.
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
        
        # Create TextWidgets for label and piece letter
        self._label_text = TextWidget(x=0, y=2, width=width, height=14,
                                       text="BRAIN:", font_size=12,
                                       justify=Justify.CENTER, transparent=True)
        self._piece_text = TextWidget(x=0, y=16, width=width, height=56,
                                       text="", font_size=48,
                                       justify=Justify.CENTER, transparent=True)
    
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
        """Render the brain hint widget using TextWidgets.
        
        Returns:
            PIL Image with the rendered widget
        """
        # Return cached image if available
        if self._last_rendered is not None:
            return self._last_rendered
        
        img = Image.new("1", (self.width, self.height), 255)
        
        if self._piece_letter:
            # Draw "BRAIN:" label at top directly onto image
            self._label_text.draw_on(img, 0, 2)
            
            # Draw large piece letter centered directly onto image
            self._piece_text.set_text(self._piece_letter)
            self._piece_text.draw_on(img, 0, 16)
        
        # Cache the rendered image
        self._last_rendered = img
        return img
