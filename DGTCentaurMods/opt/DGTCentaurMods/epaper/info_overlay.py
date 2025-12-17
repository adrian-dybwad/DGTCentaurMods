"""
Information overlay widget for displaying temporary messages.

Displays a prominent message overlay at a specified position,
typically over the analysis widget area. Auto-hides after a
specified duration or on the next move.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
from .text import TextWidget, Justify
import threading
import logging

log = logging.getLogger(__name__)


class InfoOverlayWidget(Widget):
    """Widget displaying temporary information messages.
    
    Positioned to overlay the analysis widget area (y=216, h=80).
    Shows a message with optional timeout for auto-hide.
    Uses TextWidget for text rendering.
    """
    
    # Default position: over analysis widget
    DEFAULT_Y = 216
    DEFAULT_HEIGHT = 80
    
    def __init__(self, x: int, y: int, width: int, height: int, update_callback):
        """Initialize info overlay widget.
        
        Args:
            x: X position
            y: Y position
            width: Widget width
            height: Widget height
            update_callback: Callback to trigger display updates. Must not be None.
        """
        super().__init__(x, y, width, height, update_callback)
        
        self._message = ""
        self._hide_timer: threading.Timer = None
        self.visible = False
        
        # Create TextWidget for message - use parent handler for child updates
        self._text_widget = TextWidget(
            0, 0, width, height, self._handle_child_update,
            text="", font_size=16,
            justify=Justify.CENTER, wrapText=True,
            transparent=True
        )
    
    def _handle_child_update(self, full: bool = False):
        """Handle update requests from child widgets by forwarding to parent callback."""
        return self._update_callback(full)
    
    def show_message(self, message: str, duration_seconds: float = 0) -> None:
        """Show a message, optionally auto-hiding after a duration.
        
        Args:
            message: The message to display.
            duration_seconds: If > 0, auto-hide after this many seconds.
                              If 0, message stays until hide() is called.
        """
        # Cancel any existing timer
        if self._hide_timer:
            self._hide_timer.cancel()
            self._hide_timer = None
        
        self._message = message
        log.info(f"[InfoOverlayWidget] Showing message: {message}")
        
        # Show the widget
        super().show()
        
        # Set up auto-hide timer if duration specified
        if duration_seconds > 0:
            self._hide_timer = threading.Timer(duration_seconds, self._auto_hide)
            self._hide_timer.daemon = True
            self._hide_timer.start()
    
    def _auto_hide(self):
        """Auto-hide callback from timer."""
        log.debug("[InfoOverlayWidget] Auto-hiding after timeout")
        self.hide()
    
    def hide(self) -> None:
        """Hide the overlay widget."""
        if self._hide_timer:
            self._hide_timer.cancel()
            self._hide_timer = None
        
        if self.visible:
            self._message = ""
            log.debug("[InfoOverlayWidget] Hiding overlay")
            super().hide()
    
    def stop(self) -> None:
        """Stop the widget and cleanup timer."""
        if self._hide_timer:
            self._hide_timer.cancel()
            self._hide_timer = None
        super().stop()
    
    def draw_on(self, img: Image.Image, draw_x: int, draw_y: int) -> None:
        """Draw the info overlay.
        
        Draws a white background with black border and centered text.
        """
        if not self.visible or not self._message:
            return
        
        draw = ImageDraw.Draw(img)
        
        # Draw white background with black border
        draw.rectangle(
            [(draw_x, draw_y), (draw_x + self.width - 1, draw_y + self.height - 1)],
            fill=255, outline=0, width=2
        )
        
        # Draw message centered
        self._text_widget.set_text(self._message)
        # Center vertically
        text_y = draw_y + (self.height - self._text_widget.height) // 2
        self._text_widget.draw_on(img, draw_x, text_y, text_color=0)
