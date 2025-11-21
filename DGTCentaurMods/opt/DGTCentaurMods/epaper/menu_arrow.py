"""
Menu arrow widget that handles selection and key events.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
from typing import Optional, Callable
import threading
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log


class MenuArrowWidget(Widget):
    """Widget that displays a menu arrow and handles key-based navigation."""
    
    def __init__(self, x: int, y: int, width: int, height: int,
                 row_height: int, num_entries: int):
        """
        Initialize menu arrow widget.
        
        Args:
            x: X position of widget
            y: Y position of widget (absolute screen position)
            width: Widget width (arrow column width + vertical line)
            height: Widget height (total height of all selectable rows)
            row_height: Height of each menu row
            num_entries: Number of selectable menu entries
        """
        super().__init__(x, y, width, height)
        self.row_height = row_height
        self.num_entries = num_entries
        self.selected_index = 0
        self._key_callback: Optional[Callable] = None
        self._original_key_callback: Optional[Callable] = None
        self._selection_event = threading.Event()
        self._selection_result: Optional[str] = None
        self._active = False
        
    def max_index(self) -> int:
        """Get maximum valid selection index."""
        return max(0, self.num_entries - 1)
    
    def set_selection(self, index: int) -> None:
        """Set the current selection index."""
        new_index = max(0, min(index, self.max_index()))
        if new_index != self.selected_index:
            self.selected_index = new_index
            self._last_rendered = None
            self.request_update(full=False)
    
    def _row_top(self, idx: int) -> int:
        """Calculate relative Y position within widget for a given row index.
        
        Uses total height and current index to position the arrow.
        """
        return idx * self.row_height
    
    def render(self) -> Image.Image:
        """Render the arrow column with arrow at current selection."""
        img = Image.new("1", (self.width, self.height), 255)  # White background
        draw = ImageDraw.Draw(img)
        
        # Clear entire arrow box area
        draw.rectangle((0, 0, self.width, self.height), fill=255, outline=255)
        
        # Draw arrow at selected position (within the arrow box)
        if self.num_entries > 0 and self.selected_index < self.num_entries:
            selected_top = self._row_top(self.selected_index)
            # Arrow is drawn on the left side, leaving space for vertical line on right
            arrow_width = self.width - 1  # Leave 1 pixel for vertical line
            draw.polygon(
                [
                    (2, selected_top + 2),
                    (2, selected_top + self.row_height - 2),
                    (arrow_width - 3, selected_top + (self.row_height // 2)),
                ],
                fill=0,
            )
        
        # Draw vertical line on the rightmost side of the widget
        draw.line((self.width - 1, 0, self.width - 1, self.height - 1), fill=0, width=1)
        
        return img
    
    def handle_key(self, key_id):
        """Handle key press events. Called from menu's keyPressed function."""
        if not self._active:
            return False  # Not handling keys
        
        log.info(f">>> MenuArrowWidget.handle_key: key={key_id}, selected_index={self.selected_index}")
        
        if key_id == board.Key.DOWN:
            new_index = self.selected_index + 1
            if new_index > self.max_index():
                new_index = 0
            self._update_selection(new_index)
            return True  # Handled
        
        elif key_id == board.Key.UP:
            new_index = self.selected_index - 1
            if new_index < 0:
                new_index = self.max_index()
            self._update_selection(new_index)
            return True  # Handled
        
        elif key_id == board.Key.TICK:
            # Selection confirmed
            self._selection_result = "SELECTED"
            self._selection_event.set()
            return True  # Handled
        
        elif key_id == board.Key.BACK:
            # Back pressed
            self._selection_result = "BACK"
            self._selection_event.set()
            return True  # Handled
        
        elif key_id == board.Key.HELP:
            # Help pressed
            self._selection_result = "HELP"
            self._selection_event.set()
            return True  # Handled
        
        elif key_id == board.Key.LONG_PLAY:
            # Shutdown
            board.shutdown()
            return True  # Handled
        
        return False  # Not handled
    
    def _update_selection(self, new_index: int) -> None:
        """Update selection and refresh display using widget mechanism."""
        if new_index != self.selected_index:
            self.selected_index = new_index
            self._last_rendered = None  # Invalidate cache so render() will regenerate
            # Use widget mechanism: request_update() triggers Manager.update()
            # which will call render() on this widget and paste it to framebuffer
            self.request_update(full=False)
    
    def _get_manager(self):
        """Get the display manager instance."""
        try:
            from DGTCentaurMods.menu import _get_display_manager
            return _get_display_manager()
        except:
            return None
    
    def wait_for_selection(self, initial_index: int = 0) -> str:
        """
        Block and wait for user selection via key presses.
        
        This method:
        1. Sets up key event handling
        2. Blocks waiting for a selection event (TICK, BACK, HELP)
        3. Updates arrow position based on UP/DOWN keys
        4. Returns the selection result
        
        Args:
            initial_index: Initial selection index
            
        Returns:
            "SELECTED" if TICK was pressed
            "BACK" if BACK was pressed
            "HELP" if HELP was pressed
        """
        # Set initial selection
        self.set_selection(initial_index)
        
        # Activate key handling
        self._active = True
        self._selection_result = None
        self._selection_event.clear()
        
        # Register this widget as the active arrow widget
        try:
            import DGTCentaurMods.menu as menu_module
            menu_module._active_arrow_widget = self
        except Exception as e:
            log.error(f"Error registering arrow widget: {e}")
        
        # Wait for selection event
        try:
            self._selection_event.wait()
            result = self._selection_result or "BACK"
            return result
        finally:
            # Deactivate
            self._active = False
            try:
                import DGTCentaurMods.menu as menu_module
                menu_module._active_arrow_widget = None
            except:
                pass

