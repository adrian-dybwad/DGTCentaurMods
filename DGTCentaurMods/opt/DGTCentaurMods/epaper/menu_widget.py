"""
Menu widget that displays a menu with title, entries, arrow navigation, and description.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
from .menu_arrow import MenuArrowWidget
from .text import TextWidget
from typing import Optional, Callable, List, Sequence
from dataclasses import dataclass
import threading
from DGTCentaurMods.board.logging import log

# Import AssetManager - use direct module import to avoid circular import
try:
    from DGTCentaurMods.managers.asset import AssetManager
except ImportError:
    AssetManager = None

# Constants matching menu.py
STATUS_BAR_HEIGHT = 16
TITLE_GAP = 8
TITLE_HEIGHT = 24
TITLE_TOP = STATUS_BAR_HEIGHT + TITLE_GAP
MENU_TOP = TITLE_TOP + TITLE_HEIGHT
MENU_ROW_HEIGHT = 24
MENU_BODY_TOP_WITH_TITLE = MENU_TOP
MENU_BODY_TOP_NO_TITLE = STATUS_BAR_HEIGHT + TITLE_GAP
DESCRIPTION_GAP = 8


@dataclass
class MenuEntry:
    key: str
    label: str
    description: Optional[str] = None


class MenuWidget(Widget):
    """Widget that displays a complete menu with title, entries, arrow navigation, and description."""
    
    def __init__(self, x: int, y: int, width: int, height: int,
                 title: Optional[str],
                 entries: Sequence[MenuEntry],
                 description: Optional[str] = None,
                 selected_index: int = 0,
                 register_callback: Optional[Callable[['MenuWidget'], None]] = None,
                 unregister_callback: Optional[Callable[[], None]] = None,
                 background_shade: int = 2):
        """
        Initialize menu widget.
        
        Args:
            x: X position of widget
            y: Y position of widget (absolute screen position)
            width: Widget width
            height: Widget height
            title: Optional menu title
            entries: List of menu entries to display
            description: Optional menu-level description (fallback if entries don't have descriptions)
            selected_index: Initial selected index
            register_callback: Optional callback to register this widget as active (called with self)
            unregister_callback: Optional callback to unregister this widget (called with no args)
            background_shade: Dithered background shade 0-16 (default 2 = ~12.5% grey)
        """
        super().__init__(x, y, width, height, background_shade=background_shade)
        self.title = title or ""
        self.entries: List[MenuEntry] = list(entries)
        self.description = (description or "").strip()
        self.row_height = MENU_ROW_HEIGHT
        self.arrow_width = 20
        self.selected_index = selected_index
        self._register_callback = register_callback
        self._unregister_callback = unregister_callback

        log.info(f">>> MenuWidget.__init__: x={x}, y={y}, width={width}, height={height}, title={title}, entries={entries}, description={description}, selected_index={selected_index}")
        
        # Calculate body top position relative to widget (widget is at y=STATUS_BAR_HEIGHT)
        # MENU_BODY_TOP_WITH_TITLE is absolute screen position, so subtract widget's y
        if self.title:
            self.body_top = MENU_BODY_TOP_WITH_TITLE - self.y
        else:
            self.body_top = MENU_BODY_TOP_NO_TITLE - self.y
        
        # Internal widgets (not added to manager, rendered by this widget)
        self._title_widget: Optional[TextWidget] = None
        self._entry_widgets: List[TextWidget] = []
        self._description_widget: Optional[TextWidget] = None
        self._arrow_widget: Optional[MenuArrowWidget] = None
        
        # Selection event handling
        self._selection_event = threading.Event()
        self._selection_result: Optional[str] = None
        self._active = False
        
        # Create internal widgets
        self._create_widgets()
    
    def _create_widgets(self) -> None:
        """Create internal widgets for title, entries, description, and arrow.
        
        All positions are relative to the MenuWidget's position (self.x, self.y).
        """
        # Create title widget if present (transparent to inherit menu background)
        if self.title:
            title_text = f"[ {self.title} ]"
            # Title is positioned above body_top, relative to widget
            title_top = self.body_top - TITLE_HEIGHT
            self._title_widget = TextWidget(0, title_top, self.width, TITLE_HEIGHT, title_text,
                                           font_size=18)
        
        # Create entry widgets (transparent to inherit menu background)
        text_x = self.arrow_width + 4
        text_width = self.width - text_x
        self._entry_widgets = []
        for idx, entry in enumerate(self.entries):
            # Position relative to widget
            top = self.body_top + (idx * self.row_height)
            entry_widget = TextWidget(text_x, top, text_width, self.row_height, entry.label,
                                     font_size=16)
            self._entry_widgets.append(entry_widget)
        
        # Create arrow widget
        arrow_box_top = self.body_top
        arrow_widget_height = len(self.entries) * self.row_height if self.entries else self.row_height
        
        def arrow_register_callback(arrow_widget):
            """Callback when arrow widget registers itself."""
            if self._register_callback:
                self._register_callback(self)
        
        def arrow_unregister_callback():
            """Callback when arrow widget unregisters itself."""
            if self._unregister_callback:
                self._unregister_callback()
        
        self._arrow_widget = MenuArrowWidget(
            x=0,
            y=arrow_box_top,
            width=self.arrow_width + 1,  # +1 for vertical line
            height=arrow_widget_height,
            row_height=self.row_height,
            num_entries=len(self.entries),
            register_callback=arrow_register_callback,
            unregister_callback=arrow_unregister_callback,
        )
        
        # Set initial selection
        self._arrow_widget.set_selection(self.selected_index)
    
    def _row_top(self, idx: int) -> int:
        """Calculate Y position for a given row index (relative to widget)."""
        return self.body_top + (idx * self.row_height)
    
    def _get_description_for_index(self, index: int) -> str:
        """Get description for a given entry index."""
        if self.entries and index < len(self.entries):
            entry = self.entries[index]
            if entry.description:
                return entry.description
        return self.description
    
    def max_index(self) -> int:
        """Get maximum valid selection index."""
        return max(0, len(self.entries) - 1)
    
    def set_selection(self, index: int) -> None:
        """Set the current selection index."""
        new_index = max(0, min(index, self.max_index()))
        if new_index != self.selected_index:
            self.selected_index = new_index
            if self._arrow_widget:
                self._arrow_widget.set_selection(new_index)
            self._last_rendered = None
            self.request_update(full=False)
    
    def render(self) -> Image.Image:
        """Render the complete menu including title, entries, arrow, and description."""
        img = self.create_background_image()
        
        # Helper to paste widget with mask support for transparency
        def paste_widget(widget):
            widget_img = widget.render()
            mask = widget.get_mask()
            if mask:
                img.paste(widget_img, (widget.x, widget.y), mask)
            else:
                img.paste(widget_img, (widget.x, widget.y))
        
        # Render title widget if present (positions are already relative to widget)
        if self._title_widget:
            paste_widget(self._title_widget)
        
        # Render entry widgets (positions are already relative to widget)
        for entry_widget in self._entry_widgets:
            paste_widget(entry_widget)
        
        # Render arrow widget (positions are already relative to widget)
        if self._arrow_widget:
            paste_widget(self._arrow_widget)
        
        # Create description widget (transparent by default)
        desc_top = self.body_top + (len(self.entries) * self.row_height) + DESCRIPTION_GAP
        desc_width = self.width - 10  # Leave 5px margin on each side
        initial_desc = self._get_description_for_index(self.selected_index)
        if initial_desc:
            _description_widget = TextWidget(5, desc_top, desc_width, 150, initial_desc,
                                                  font_size=14, wrapText=True)
            paste_widget(_description_widget)
        
        return img
    
    def handle_key(self, key_id):
        """Handle key press events. Delegates to arrow widget."""
        # Always delegate to arrow widget - it manages its own active state
        # The arrow widget's active state is set in wait_for_selection()
        if self._arrow_widget:
            handled = self._arrow_widget.handle_key(key_id)
            if handled:
                # Update our selection index to match arrow widget
                self.set_selection(self._arrow_widget.selected_index)
                # Check if selection event was triggered
                if self._arrow_widget._selection_event.is_set():
                    self._selection_result = self._arrow_widget._selection_result
                    self._selection_event.set()
            return handled
        
        return False
    
    def wait_for_selection(self, initial_index: int = 0) -> str:
        """
        Block and wait for user selection via key presses.
        
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
        
        # Register this widget as active
        if self._register_callback:
            try:
                self._register_callback(self)
                log.info(f">>> MenuWidget.wait_for_selection: registered as active menu widget, initial_index={initial_index}")
            except Exception as e:
                log.error(f"Error registering menu widget: {e}")
        
        # Use arrow widget's wait_for_selection if available
        if self._arrow_widget:
            try:
                result = self._arrow_widget.wait_for_selection(initial_index)
                log.info(f">>> MenuWidget.wait_for_selection: arrow widget returned result='{result}'")
                return result
            finally:
                self._active = False
                if self._unregister_callback:
                    try:
                        self._unregister_callback()
                    except Exception as e:
                        log.error(f"Error unregistering menu widget: {e}")
        else:
            # Fallback: wait on our own event
            log.info(">>> MenuWidget.wait_for_selection: waiting for key press...")
            try:
                self._selection_event.wait()
                result = self._selection_result or "BACK"
                log.info(f">>> MenuWidget.wait_for_selection: event received, result='{result}'")
                return result
            finally:
                self._active = False
                log.info(">>> MenuWidget.wait_for_selection: deactivating menu widget")
                if self._unregister_callback:
                    try:
                        self._unregister_callback()
                    except Exception as e:
                        log.error(f"Error unregistering menu widget: {e}")

