"""
Unified menu widget that handles all menu UI rendering including arrow, items, and description.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
from .text import TextWidget
from typing import Optional, Callable, List, Sequence
from dataclasses import dataclass
import threading
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log


@dataclass
class MenuEntry:
    """Represents a single menu entry."""
    key: str
    label: str
    description: Optional[str] = None  # Optional per-entry description


class MenuWidget(Widget):
    """Unified widget that renders complete menu UI including arrow, items, title, and description."""
    
    # Constants matching menu.py
    STATUS_BAR_HEIGHT = 16
    TITLE_GAP = 8
    TITLE_HEIGHT = 26
    MENU_ROW_HEIGHT = 20
    DESCRIPTION_GAP = 8
    ARROW_WIDTH = 20
    
    def __init__(self, x: int, y: int, width: int, height: int,
                 title: Optional[str],
                 entries: Sequence[MenuEntry],
                 selected_index: int = 0,
                 menu_description: Optional[str] = None,
                 register_callback: Optional[Callable[['MenuWidget'], None]] = None,
                 unregister_callback: Optional[Callable[[], None]] = None):
        """
        Initialize menu widget.
        
        Args:
            x: X position of widget (typically 0)
            y: Y position of widget (typically STATUS_BAR_HEIGHT)
            width: Widget width (typically 128)
            height: Widget height (full screen height minus status bar)
            title: Optional menu title
            entries: List of menu entries to display
            selected_index: Initial selected index
            menu_description: Optional menu-level description (fallback if entries don't have descriptions)
            register_callback: Optional callback to register this widget as active (called with self)
            unregister_callback: Optional callback to unregister this widget (called with no args)
        """
        super().__init__(x, y, width, height)
        self.title = title or ""
        self.entries: List[MenuEntry] = list(entries)
        self.menu_description = (menu_description or "").strip()
        self.selected_index = max(0, min(selected_index, self.max_index()))
        self.row_height = self.MENU_ROW_HEIGHT
        self.arrow_width = self.ARROW_WIDTH
        
        # Calculate layout positions (relative to widget's y position)
        # Since widget starts at y=STATUS_BAR_HEIGHT, body_top is relative to widget start
        self.body_top = (self.TITLE_GAP + self.TITLE_HEIGHT) if self.title else self.TITLE_GAP
        self.text_x = self.arrow_width + 4  # Position text after arrow column with gap
        
        # Key handling
        self._selection_event = threading.Event()
        self._selection_result: Optional[str] = None
        self._active = False
        self._register_callback = register_callback
        self._unregister_callback = unregister_callback
        
        # Internal widgets (not added to manager, rendered by this widget)
        self._title_widget: Optional[TextWidget] = None
        self._entry_widgets: List[TextWidget] = []
        self._description_widget: Optional[TextWidget] = None
        
        # Build internal widgets
        self._build_widgets()
    
    def max_index(self) -> int:
        """Get maximum valid selection index."""
        return max(0, len(self.entries) - 1)
    
    def set_selection(self, index: int) -> None:
        """Set the current selection index."""
        new_index = max(0, min(index, self.max_index()))
        if new_index != self.selected_index:
            self.selected_index = new_index
            self._update_description()
            self._last_rendered = None
            self.request_update(full=False)
    
    def _row_top(self, idx: int) -> int:
        """Calculate absolute Y position for a given row index."""
        return self.y + self.body_top + (idx * self.row_height)
    
    def _row_top_relative(self, idx: int) -> int:
        """Calculate relative Y position within widget for a given row index."""
        return self.body_top + (idx * self.row_height)
    
    def _build_widgets(self) -> None:
        """Build internal widgets for title, entries, and description."""
        # Build title widget if present
        if self.title:
            title_text = f"[ {self.title} ]"
            title_top = self.y + self.TITLE_GAP  # Absolute position
            self._title_widget = TextWidget(
                self.x, title_top, self.width, self.TITLE_HEIGHT,
                title_text, background=3, font_size=18
            )
        
        # Build entry widgets
        self._entry_widgets = []
        text_width = self.width - self.text_x
        for idx, entry in enumerate(self.entries):
            top = self._row_top(idx)
            entry_widget = TextWidget(
                self.x + self.text_x, top, text_width, self.row_height,
                entry.label, background=0, font_size=16
            )
            self._entry_widgets.append(entry_widget)
        
        # Build description widget
        self._update_description()
    
    def _update_description(self) -> None:
        """Update description widget to show description for selected entry."""
        # Get description for selected entry
        desc_text = ""
        if self.entries and self.selected_index < len(self.entries):
            entry = self.entries[self.selected_index]
            if entry.description:
                desc_text = entry.description
        
        # Fallback to menu-level description if no per-entry description
        if not desc_text:
            desc_text = self.menu_description
        
        # Create or update description widget
        if desc_text:
            # Calculate description position (absolute coordinates)
            desc_top_absolute = self.y + self.body_top + (len(self.entries) * self.row_height) + self.DESCRIPTION_GAP
            desc_width = self.width - 10  # Leave 5px margin on each side
            
            if self._description_widget is None:
                # Create new description widget (absolute coordinates)
                self._description_widget = TextWidget(
                    self.x + 5, desc_top_absolute, desc_width, 150,
                    desc_text, background=0, font_size=14, wrapText=True
                )
            else:
                # Update existing description widget
                self._description_widget.set_text(desc_text)
        elif self._description_widget is not None:
            # Clear description if no description available
            self._description_widget.set_text("")
    
    def render(self) -> Image.Image:
        """Render the complete menu including title, entries, arrow, and description."""
        img = Image.new("1", (self.width, self.height), 255)  # White background
        draw = ImageDraw.Draw(img)
        
        # Render title widget if present
        if self._title_widget:
            title_img = self._title_widget.render()
            title_y = self._title_widget.y - self.y  # Convert to relative coordinates
            img.paste(title_img, (0, title_y))
        
        # Render entry widgets
        for entry_widget in self._entry_widgets:
            entry_img = entry_widget.render()
            entry_y = entry_widget.y - self.y  # Convert to relative coordinates
            img.paste(entry_img, (entry_widget.x - self.x, entry_y))
        
        # Render arrow at selected position
        if self.num_entries > 0 and self.selected_index < self.num_entries:
            selected_top = self._row_top_relative(self.selected_index)  # Relative to widget
            arrow_width = self.arrow_width - 1  # Leave 1 pixel for vertical line
            draw.polygon(
                [
                    (2, selected_top + 2),
                    (2, selected_top + self.row_height - 2),
                    (arrow_width - 3, selected_top + (self.row_height // 2)),
                ],
                fill=0,
            )
        
        # Draw vertical line on the right side of arrow column
        arrow_column_right = self.arrow_width
        menu_height = len(self.entries) * self.row_height if self.entries else 0
        if menu_height > 0:
            arrow_column_top = self.body_top  # Relative to widget
            draw.line(
                (arrow_column_right - 1, arrow_column_top,
                 arrow_column_right - 1, arrow_column_top + menu_height - 1),
                fill=0,
                width=1
            )
        
        # Render description widget if present
        if self._description_widget:
            desc_img = self._description_widget.render()
            desc_y = self._description_widget.y - self.y  # Convert to relative coordinates
            img.paste(desc_img, (self._description_widget.x - self.x, desc_y))
        
        return img
    
    @property
    def num_entries(self) -> int:
        """Get number of menu entries."""
        return len(self.entries)
    
    def handle_key(self, key_id):
        """Handle key press events. Called from menu's keyPressed function."""
        if not self._active:
            return False  # Not handling keys
        
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

