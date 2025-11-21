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
                 row_height: int, body_top: int, num_entries: int,
                 title: Optional[str] = None, title_height: int = 0):
        """
        Initialize menu arrow widget.
        
        Args:
            x: X position
            y: Y position
            width: Widget width (arrow column width)
            height: Widget height (full menu area height)
            row_height: Height of each menu row
            body_top: Y position where menu body starts
            num_entries: Number of menu entries
            title: Optional menu title (for redrawing on refresh)
            title_height: Height of title area if present
        """
        super().__init__(x, y, width, height)
        self.row_height = row_height
        self.body_top = body_top
        self.num_entries = num_entries
        self.title = title
        self.title_height = title_height
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
        """Calculate Y position for a given row index."""
        return self.body_top + (idx * self.row_height)
    
    def render(self) -> Image.Image:
        """Render the arrow column with arrow at current selection."""
        img = Image.new("1", (self.width, self.height), 255)  # White background
        draw = ImageDraw.Draw(img)
        
        # Clear arrow column area
        arrow_region = (0, self.body_top - self.y, self.width, self.height)
        draw.rectangle(arrow_region, fill=255, outline=255)
        
        # Draw arrow at selected position
        if self.num_entries > 0:
            selected_top = self._row_top(self.selected_index) - self.y
            draw.polygon(
                [
                    (2, selected_top + 2),
                    (2, selected_top + self.row_height - 2),
                    (self.width - 3, selected_top + (self.row_height // 2)),
                ],
                fill=0,
            )
        
        # Draw vertical line
        line_y1 = self.body_top - self.y
        line_y2 = self.height - 1
        draw.line((self.width, line_y1, self.width, line_y2), fill=0, width=1)
        
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
        """Update selection and refresh display."""
        if new_index != self.selected_index:
            self.selected_index = new_index
            self._last_rendered = None
            # Draw arrow directly to framebuffer and submit
            manager = self._get_manager()
            if manager:
                canvas = manager._framebuffer.get_canvas()
                draw = ImageDraw.Draw(canvas)
                
                # Calculate absolute positions (body_top is relative to widget y)
                absolute_body_top = self.y + self.body_top
                
                # Clear arrow column
                arrow_region = (self.x, absolute_body_top, self.x + self.width, 295)
                draw.rectangle(arrow_region, fill=255, outline=255)
                
                # Draw arrow at new position (row_top is relative to widget y, so add self.y)
                arrow_top = self.y + self._row_top(self.selected_index)
                draw.polygon(
                    [
                        (self.x + 2, arrow_top + 2),
                        (self.x + 2, arrow_top + self.row_height - 2),
                        (self.x + self.width - 3, arrow_top + (self.row_height // 2)),
                    ],
                    fill=0,
                )
                
                # Draw vertical line
                draw.line((self.x + self.width, absolute_body_top, self.x + self.width, 295), fill=0, width=1)
                
                # Submit immediate partial refresh
                manager._scheduler.submit(full=False, immediate=True)
    
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

