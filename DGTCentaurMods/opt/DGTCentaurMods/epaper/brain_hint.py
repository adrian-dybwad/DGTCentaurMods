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
    
    def __init__(self, x: int, y: int, width: int, height: int, update_callback):
        """Initialize the brain hint widget.
        
        Args:
            x: X position on display
            y: Y position on display
            width: Widget width
            height: Widget height
            update_callback: Callback to trigger display updates. Must not be None.
        """
        super().__init__(x, y, width, height, update_callback)
        self._piece_letter = ""  # Empty = no hint shown
        
        # Create TextWidgets for label and piece letter - use parent handler for child updates
        self._label_text = TextWidget(0, 2, width, 14, self._handle_child_update,
                                       text="BRAIN:", font_size=12,
                                       justify=Justify.CENTER, transparent=True)
        self._piece_text = TextWidget(0, 16, width, 56, self._handle_child_update,
                                       text="", font_size=48,
                                       justify=Justify.CENTER, transparent=True)
    
    def _handle_child_update(self, full: bool = False, immediate: bool = False):
        """Handle update requests from child widgets by forwarding to parent callback."""
        return self._update_callback(full, immediate)
    
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
            self.invalidate_cache()
            self.request_update(full=False)
    
    def clear(self) -> None:
        """Clear the hint display."""
        self.set_piece("")
    
    def render(self, sprite: Image.Image) -> None:
        """Render the brain hint widget using TextWidgets."""
        # Draw background
        self.draw_background_on_sprite(sprite)
        
        if self._piece_letter:
            # Draw "BRAIN:" label at top directly onto sprite
            self._label_text.draw_on(sprite, 0, 2)
            
            # Draw large piece letter centered directly onto sprite
            self._piece_text.set_text(self._piece_letter)
            self._piece_text.draw_on(sprite, 0, 16)
