"""
Menu widget that renders title, entries, arrow, and description.
"""

import os
import threading
from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
from .text import TextWidget
from typing import List, Optional, Sequence, Callable
from dataclasses import dataclass

try:
    from DGTCentaurMods.display.ui_components import AssetManager
except ImportError:
    AssetManager = None

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

try:
    from DGTCentaurMods.board import board
except ImportError:
    board = None


@dataclass
class MenuEntry:
    key: str
    label: str
    description: Optional[str] = None


class MenuWidget(Widget):
    """Widget that renders a complete menu with title, entries, arrow, and description."""
    
    # Constants matching menu.py
    STATUS_BAR_HEIGHT = 16
    TITLE_GAP = 8
    TITLE_HEIGHT = 24
    MENU_ROW_HEIGHT = 20
    DESCRIPTION_GAP = 8
    ARROW_WIDTH = 20
    
    def __init__(self, x: int, y: int, width: int, height: int,
                 title: Optional[str] = None,
                 entries: Sequence[MenuEntry] = None,
                 selected_index: int = 0,
                 menu_description: Optional[str] = None,
                 register_callback: Optional[Callable[['MenuWidget'], None]] = None,
                 unregister_callback: Optional[Callable[[], None]] = None):
        """
        Initialize menu widget.
        
        Args:
            x: X position
            y: Y position
            width: Widget width (typically 128 for e-paper)
            height: Widget height (typically 296 for e-paper)
            title: Optional menu title
            entries: List of menu entries
            selected_index: Currently selected entry index
            menu_description: Optional menu-level description (used as fallback if entry has no description)
            register_callback: Optional callback to register this widget as active (called with self)
            unregister_callback: Optional callback to unregister this widget (called with no args)
        """
        super().__init__(x, y, width, height)
        self.title = title or ""
        self.entries: List[MenuEntry] = list(entries) if entries else []
        self.selected_index = max(0, min(selected_index, len(self.entries) - 1) if self.entries else 0)
        self.menu_description = (menu_description or "").strip()  # Menu-level description fallback
        
        # Key handling state
        self._active = False
        self._selection_event = threading.Event()
        self._selection_result: Optional[str] = None
        self._register_callback = register_callback
        self._unregister_callback = unregister_callback
        self._arrow_widget_callback: Optional[Callable[[int], None]] = None  # Callback to update arrow widget
        
        # Calculate layout positions
        self._title_top = self.STATUS_BAR_HEIGHT + self.TITLE_GAP if self.title else 0
        self._menu_top = self._title_top + (self.TITLE_HEIGHT if self.title else 0)
        self._text_x = self.ARROW_WIDTH + 4  # Text starts after arrow column (was +2, now +4 to match old implementation)
    
    def set_selection(self, index: int) -> None:
        """Set the selected entry index and trigger re-render."""
        new_index = max(0, min(index, len(self.entries) - 1) if self.entries else 0)
        if new_index != self.selected_index:
            self.selected_index = new_index
            self._last_rendered = None  # Invalidate cache
            
            # Update arrow widget if callback provided
            if self._arrow_widget_callback:
                self._arrow_widget_callback(new_index)
            
            self.request_update(full=False)
    
    def set_entries(self, entries: Sequence[MenuEntry], selected_index: int = 0) -> None:
        """Update menu entries and trigger re-render."""
        self.entries = list(entries)
        self.set_selection(selected_index)
    
    def max_index(self) -> int:
        """Get maximum valid selection index."""
        return max(0, len(self.entries) - 1)
    
    def handle_key(self, key_id) -> bool:
        """Handle key press events. Called from menu's keyPressed function."""
        if not self._active:
            return False  # Not handling keys
        
        if not board:
            return False
        
        log.info(f">>> MenuWidget.handle_key: key={key_id}, selected_index={self.selected_index}")
        
        if key_id == board.Key.DOWN:
            new_index = self.selected_index + 1
            if new_index > self.max_index():
                new_index = 0
            log.info(f">>> MenuWidget.handle_key: new_index={new_index}")
            self.set_selection(new_index)
            return True  # Handled
        
        elif key_id == board.Key.UP:
            new_index = self.selected_index - 1
            if new_index < 0:
                new_index = self.max_index()
            log.info(f">>> MenuWidget.handle_key: new_index={new_index}")
            self.set_selection(new_index)
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
            if board:
                board.shutdown()
            return True  # Handled
        
        return False  # Not handled
    
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
        
        # Register this widget as the active menu widget
        if self._register_callback:
            try:
                self._register_callback(self)
                log.info(f">>> MenuWidget.wait_for_selection: registered as active menu widget, initial_index={initial_index}")
            except Exception as e:
                log.error(f"Error registering menu widget: {e}")
        
        # Wait for selection event
        log.info(">>> MenuWidget.wait_for_selection: waiting for key press...")
        try:
            self._selection_event.wait()
            result = self._selection_result or "BACK"
            log.info(f">>> MenuWidget.wait_for_selection: event received, result='{result}'")
            return result
        finally:
            # Deactivate
            self._active = False
            log.info(">>> MenuWidget.wait_for_selection: deactivating menu widget")
            if self._unregister_callback:
                try:
                    self._unregister_callback()
                except Exception as e:
                    log.error(f"Error unregistering menu widget: {e}")
    
    def _row_top(self, idx: int) -> int:
        """Calculate Y position for a menu row."""
        return self._menu_top + (idx * self.MENU_ROW_HEIGHT)
    
    
    def render(self) -> Image.Image:
        """Render the complete menu: title, entries, arrow, and description."""
        img = Image.new("1", (self.width, self.height), 255)  # White background
        draw = ImageDraw.Draw(img)
        
        # Draw title if present using TextWidget with background
        if self.title:
            title_text = f"[ {self.title} ]"
            title_y = self._title_top
            
            # Use TextWidget to render title with background dithering (background=3 = medium dither)
            title_widget = TextWidget(
                x=0,
                y=title_y,
                width=self.width,
                height=self.TITLE_HEIGHT,
                text=title_text,
                background=3,  # Medium dither (checkerboard pattern)
                font_size=18,
                wrapText=False
            )
            
            # Render the title widget and paste it into the menu image
            title_image = title_widget.render()
            img.paste(title_image, (0, title_y))
        
        # Draw menu entries and arrow
        text_width = self.width - self._text_x
        for idx, entry in enumerate(self.entries):
            row_y = self._row_top(idx)
            
            # Use TextWidget to render entry text (matching old implementation)
            entry_widget = TextWidget(
                x=self._text_x,
                y=row_y,
                width=text_width,
                height=self.MENU_ROW_HEIGHT,
                text=entry.label,
                background=0,  # White background (no dithering)
                font_size=16,
                wrapText=False
            )
            
            # Render the entry widget and paste it into the menu image
            entry_image = entry_widget.render()
            img.paste(entry_image, (self._text_x, row_y))
        
        # Draw description for selected entry (or menu-level description as fallback)
        desc_text = None
        if self.entries and self.selected_index < len(self.entries):
            entry = self.entries[self.selected_index]
            # Use entry description if available, otherwise fall back to menu-level description
            desc_text = entry.description if entry.description else self.menu_description
        elif self.menu_description:
            # No entries or invalid selection, but we have a menu-level description
            desc_text = self.menu_description
        
        if desc_text:
            desc_top = self._row_top(len(self.entries)) + self.DESCRIPTION_GAP
            desc_width = self.width - 10  # 5px margin on each side
            desc_height = self.height - desc_top  # Available height for description
            
            # Use TextWidget to render wrapped description text
            desc_widget = TextWidget(
                x=5,  # 5px margin from left
                y=desc_top,
                width=desc_width,
                height=desc_height,
                text=desc_text,
                background=0,  # White background (no dithering)
                font_size=14,
                wrapText=True
            )
            
            # Render the description widget and paste it into the menu image
            desc_image = desc_widget.render()
            img.paste(desc_image, (5, desc_top))
        
        return img

