"""
Menu widget that renders title, entries, arrow, and description.
"""

import os
import threading
from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
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
            register_callback: Optional callback to register this widget as active (called with self)
            unregister_callback: Optional callback to unregister this widget (called with no args)
        """
        super().__init__(x, y, width, height)
        self.title = title or ""
        self.entries: List[MenuEntry] = list(entries) if entries else []
        self.selected_index = max(0, min(selected_index, len(self.entries) - 1) if self.entries else 0)
        
        # Key handling state
        self._active = False
        self._selection_event = threading.Event()
        self._selection_result: Optional[str] = None
        self._register_callback = register_callback
        self._unregister_callback = unregister_callback
        
        # Calculate layout positions
        self._title_top = self.STATUS_BAR_HEIGHT + self.TITLE_GAP if self.title else 0
        self._menu_top = self._title_top + (self.TITLE_HEIGHT if self.title else 0)
        self._text_x = self.ARROW_WIDTH + 4  # Text starts after arrow column
        
        # Load fonts
        self._title_font = self._load_font(18)
        self._entry_font = self._load_font(16)
        self._description_font = self._load_font(14)
    
    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        """Load font with fallbacks."""
        font_paths = []
        if AssetManager is not None:
            try:
                default_font_path = AssetManager.get_resource_path("Font.ttc")
                if default_font_path:
                    font_paths.append(default_font_path)
            except:
                pass
        
        font_paths.extend([
            '/opt/DGTCentaurMods/resources/Font.ttc',
            'resources/Font.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ])
        
        for path in font_paths:
            try:
                if path and os.path.exists(path):
                    return ImageFont.truetype(path, size)
            except:
                continue
        
        return ImageFont.load_default()
    
    def set_selection(self, index: int) -> None:
        """Set the selected entry index and trigger re-render."""
        new_index = max(0, min(index, len(self.entries) - 1) if self.entries else 0)
        if new_index != self.selected_index:
            self.selected_index = new_index
            self._last_rendered = None  # Invalidate cache
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
    
    def _wrap_text(self, text: str, max_width: int, font: ImageFont.FreeTypeFont) -> List[str]:
        """Wrap text to fit within max_width using the specified font."""
        words = text.split()
        if not words:
            return []
        
        lines = []
        current = words[0]
        temp_image = Image.new("1", (1, 1), 255)
        temp_draw = ImageDraw.Draw(temp_image)
        
        for word in words[1:]:
            candidate = f"{current} {word}"
            if temp_draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        
        lines.append(current)
        return lines
    
    def render(self) -> Image.Image:
        """Render the complete menu: title, entries, arrow, and description."""
        img = Image.new("1", (self.width, self.height), 255)  # White background
        draw = ImageDraw.Draw(img)
        
        # Draw title if present
        if self.title:
            title_text = f"[ {self.title} ]"
            title_y = self._title_top
            draw.text((0, title_y), title_text, font=self._title_font, fill=0)
        
        # Draw menu entries and arrow
        text_width = self.width - self._text_x
        for idx, entry in enumerate(self.entries):
            row_y = self._row_top(idx)
            
            # Draw entry text
            draw.text((self._text_x, row_y), entry.label, font=self._entry_font, fill=0)
            
            # Draw arrow if this is the selected entry
            if idx == self.selected_index:
                arrow_width = self.ARROW_WIDTH - 1  # Leave 1 pixel for vertical line
                draw.polygon(
                    [
                        (2, row_y + 2),
                        (2, row_y + self.MENU_ROW_HEIGHT - 2),
                        (arrow_width - 3, row_y + (self.MENU_ROW_HEIGHT // 2)),
                    ],
                    fill=0,
                )
        
        # Draw vertical line on the right side of arrow column
        menu_height = len(self.entries) * self.MENU_ROW_HEIGHT if self.entries else 0
        if menu_height > 0:
            draw.line((self.ARROW_WIDTH - 1, self._menu_top, self.ARROW_WIDTH - 1, 
                       self._menu_top + menu_height - 1), fill=0, width=1)
        
        # Draw description for selected entry
        if self.entries and self.selected_index < len(self.entries):
            entry = self.entries[self.selected_index]
            if entry.description:
                desc_text = entry.description
                desc_top = self._row_top(len(self.entries)) + self.DESCRIPTION_GAP
                desc_width = self.width - 10  # 5px margin on each side
                
                # Wrap text to fit width
                wrapped_lines = self._wrap_text(desc_text, desc_width, self._description_font)
                
                # Draw wrapped text
                line_height = 16  # Approximate line height for font size 14
                for line_idx, line in enumerate(wrapped_lines):
                    y_pos = desc_top + (line_idx * line_height)
                    if y_pos + line_height > self.height:
                        break  # Don't draw beyond widget height
                    draw.text((5, y_pos), line, font=self._description_font, fill=0)
        
        return img

