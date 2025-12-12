"""
Icon menu widget for e-paper display.

A menu composed of IconButtonWidget items with keyboard navigation.
Supports callbacks for selection and external key event routing.
"""

from PIL import Image
from .framework.widget import Widget
from .icon_button import IconButtonWidget
from typing import Optional, Callable, List
from dataclasses import dataclass
import threading

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# Lazy import of board module to avoid circular imports and premature hardware initialization
_board_module = None


def _get_board():
    """Lazily import and return the board module."""
    global _board_module
    if _board_module is None:
        from DGTCentaurMods.board import board
        _board_module = board
    return _board_module


@dataclass
class IconMenuEntry:
    """Configuration for a menu entry.
    
    Attributes:
        key: Unique identifier returned on selection
        label: Display text
        icon_name: Icon identifier for rendering
        enabled: Whether entry is enabled/visible
        height_ratio: Relative height weight (default 1.0, use 2.0 for double height)
        icon_size: Custom icon size in pixels (None uses default based on button height)
        layout: Button layout - 'horizontal' (icon left) or 'vertical' (icon top centered)
        font_size: Font size in pixels (default 16)
        bold: Whether to render text in bold (default False)
    """
    key: str
    label: str
    icon_name: str
    enabled: bool = True
    height_ratio: float = 1.0
    icon_size: int = None
    layout: str = "horizontal"
    font_size: int = 16
    bold: bool = False


class IconMenuWidget(Widget):
    """Widget displaying a menu of large icon buttons.
    
    Displays a vertical list of icon buttons with keyboard navigation.
    Supports UP/DOWN for navigation, TICK for selection, BACK for cancel.
    
    When there are more entries than can fit on screen (based on min_button_height),
    the menu becomes scrollable. Navigation automatically scrolls to keep the
    selected item visible.
    
    Can be used in two modes:
    1. Callback mode: Provide on_select callback, call handle_key() externally
    2. Blocking mode: Call wait_for_selection() which blocks until user selects
    
    Attributes:
        entries: List of menu entry configurations
        selected_index: Currently highlighted entry index
        scroll_offset: Index of first visible entry (for scrolling)
    """
    
    def __init__(self, x: int, y: int, width: int, height: int,
                 entries: List[IconMenuEntry],
                 selected_index: int = 0,
                 on_select: Optional[Callable[[str], None]] = None,
                 on_back: Optional[Callable[[], None]] = None,
                 button_height: int = 70,
                 button_margin: int = 4,
                 background_shade: int = 2,
                 min_button_height: int = 45):
        """Initialize icon menu widget.
        
        Args:
            x: X position of widget
            y: Y position of widget
            width: Widget width
            height: Widget height
            entries: List of menu entry configurations
            selected_index: Initial selected entry index
            on_select: Optional callback(key) when entry is selected with TICK
            on_back: Optional callback() when BACK is pressed
            button_height: Height of each button (default 70)
            button_margin: Margin around buttons, passed to each button (default 4)
            background_shade: Dithered background shade 0-16 (default 2 = ~12.5% grey)
            min_button_height: Minimum button height before scrolling (default 45)
        """
        super().__init__(x, y, width, height, background_shade=background_shade)
        
        # Filter disabled entries
        self.entries = [e for e in entries if e.enabled]
        self.selected_index = min(selected_index, max(0, len(self.entries) - 1))
        
        # Callbacks for external use
        self.on_select = on_select
        self.on_back = on_back
        
        # Layout
        self.button_height = button_height
        self.button_margin = button_margin
        self.min_button_height = min_button_height
        
        # Scrolling state
        self.scroll_offset = 0  # Index of first visible entry
        self._visible_count = 0  # Number of entries that fit on screen
        
        # Selection event handling for blocking mode
        self._selection_event = threading.Event()
        self._selection_result: Optional[str] = None
        self._active = False
        
        # Create button widgets for visible entries
        self._buttons: List[IconButtonWidget] = []
        self._calculate_visible_count()
        self._create_buttons()
        
        log.info(f"IconMenuWidget: Created with {len(self.entries)} entries, "
                 f"{self._visible_count} visible at a time")
    
    def _calculate_visible_count(self) -> None:
        """Calculate how many entries can fit on screen.
        
        Uses min_button_height to determine if scrolling is needed.
        """
        if not self.entries:
            self._visible_count = 0
            return
        
        # Calculate total height ratio if all entries were shown
        total_ratio = sum(entry.height_ratio for entry in self.entries)
        avg_ratio = total_ratio / len(self.entries)
        
        # Estimate height per unit ratio
        height_per_ratio = self.height / total_ratio if total_ratio > 0 else self.height
        
        # Check if buttons would be too small
        min_height_per_entry = self.min_button_height / avg_ratio if avg_ratio > 0 else self.min_button_height
        
        if height_per_ratio >= min_height_per_entry:
            # All entries fit without scrolling
            self._visible_count = len(self.entries)
        else:
            # Calculate how many entries fit with minimum height
            # For simplicity with variable ratios, estimate based on average
            entries_that_fit = int(self.height / self.min_button_height)
            self._visible_count = max(1, min(entries_that_fit, len(self.entries)))
    
    def _create_buttons(self) -> None:
        """Create IconButtonWidget instances for visible entries.
        
        Only creates buttons for entries from scroll_offset to 
        scroll_offset + visible_count. Buttons are placed directly 
        adjacent to each other with their own transparent margins.
        
        Button heights are proportional to their height_ratio values
        within the visible subset.
        """
        self._buttons = []
        
        if not self.entries or self._visible_count == 0:
            return
        
        # Get visible entries
        visible_start = self.scroll_offset
        visible_end = min(visible_start + self._visible_count, len(self.entries))
        visible_entries = self.entries[visible_start:visible_end]
        
        if not visible_entries:
            return
        
        # Calculate total height ratio for visible entries
        total_ratio = sum(entry.height_ratio for entry in visible_entries)
        available_height = self.height
        
        current_y = 0
        for vis_idx, entry in enumerate(visible_entries):
            # Actual index in full entries list
            actual_idx = visible_start + vis_idx
            
            # Calculate this button's height based on its ratio
            button_height = int(available_height * entry.height_ratio / total_ratio)
            
            # Determine icon size - use entry's custom size or derive from height
            if entry.icon_size is not None:
                icon_size = entry.icon_size
            else:
                # Default icon size scales with button height
                icon_size = min(36, max(20, button_height - 24))
            
            button = IconButtonWidget(
                x=0,
                y=current_y,
                width=self.width,
                height=button_height,
                key=entry.key,
                label=entry.label,
                icon_name=entry.icon_name,
                selected=(actual_idx == self.selected_index),
                margin=self.button_margin,
                icon_size=icon_size,
                layout=entry.layout,
                font_size=entry.font_size,
                bold=entry.bold
            )
            self._buttons.append(button)
            current_y += button_height
    
    def set_selection(self, index: int) -> None:
        """Set the current selection index, scrolling if needed.
        
        Automatically adjusts scroll_offset to keep the selected item visible.
        
        Args:
            index: New selection index
        """
        new_index = max(0, min(index, len(self.entries) - 1))
        if new_index == self.selected_index:
            return
        
        self.selected_index = new_index
        
        # Check if we need to scroll to keep selection visible
        needs_rebuild = False
        
        if self._visible_count < len(self.entries):
            # Scrolling is active - ensure selected item is visible
            if new_index < self.scroll_offset:
                # Selected item is above visible area - scroll up
                self.scroll_offset = new_index
                needs_rebuild = True
            elif new_index >= self.scroll_offset + self._visible_count:
                # Selected item is below visible area - scroll down
                self.scroll_offset = new_index - self._visible_count + 1
                needs_rebuild = True
        
        if needs_rebuild:
            # Rebuild buttons with new scroll position
            self._create_buttons()
        else:
            # Just update selection state on existing buttons
            visible_start = self.scroll_offset
            for vis_idx, button in enumerate(self._buttons):
                actual_idx = visible_start + vis_idx
                button.set_selected(actual_idx == self.selected_index)
        
        self._last_rendered = None
        self.request_update(full=False)
    
    def get_selected_key(self) -> Optional[str]:
        """Get the key of the currently selected entry.
        
        Returns:
            Key string of selected entry, or None if no entries
        """
        if self.entries and self.selected_index < len(self.entries):
            return self.entries[self.selected_index].key
        return None
    
    def render(self) -> Image.Image:
        """Render the menu with all buttons.
        
        Returns:
            PIL Image with rendered menu
        """
        img = self.create_background_image()
        
        # Render each button with mask for transparent margins
        for button in self._buttons:
            button_img = button.render()
            button_mask = button.get_mask()
            if button_mask:
                img.paste(button_img, (button.x, button.y), button_mask)
            else:
                img.paste(button_img, (button.x, button.y))
        
        return img
    
    def handle_key(self, key_id) -> bool:
        """Handle key press events.
        
        Routes key events to navigate menu and trigger selection.
        Can be called externally to send key events to this menu.
        
        Args:
            key_id: Key identifier from board
            
        Returns:
            True if key was handled, False otherwise
        """
        if not self._active:
            return False
        
        board = _get_board()
        
        if key_id == board.Key.UP:
            # Move up with wrap-around
            if self.selected_index > 0:
                self.set_selection(self.selected_index - 1)
            else:
                self.set_selection(len(self.entries) - 1)
            return True
        
        elif key_id == board.Key.DOWN:
            # Move down with wrap-around
            if self.selected_index < len(self.entries) - 1:
                self.set_selection(self.selected_index + 1)
            else:
                self.set_selection(0)
            return True
        
        elif key_id == board.Key.TICK:
            # Selection confirmed
            selected_key = self.get_selected_key()
            if selected_key:
                self._selection_result = selected_key
                if self.on_select:
                    self.on_select(selected_key)
            else:
                self._selection_result = "BACK"
            self._selection_event.set()
            return True
        
        elif key_id == board.Key.BACK:
            self._selection_result = "BACK"
            if self.on_back:
                self.on_back()
            self._selection_event.set()
            return True
        
        elif key_id == board.Key.HELP:
            self._selection_result = "HELP"
            self._selection_event.set()
            return True
        
        elif key_id == board.Key.LONG_PLAY:
            self._selection_result = "SHUTDOWN"
            self._selection_event.set()
            return True
        
        return False
    
    def activate(self) -> None:
        """Activate the menu for key handling.
        
        Call this before using handle_key() in callback mode.
        
        Note: Does not clear selection state if a result is already pending.
        This handles the race condition where cancel_selection() is called
        before wait_for_selection() starts waiting.
        """
        self._active = True
        # Only clear if there's no pending result (handles race with cancel_selection)
        if self._selection_result is None:
            self._selection_event.clear()
    
    def deactivate(self) -> None:
        """Deactivate the menu from key handling."""
        self._active = False
    
    def wait_for_selection(self, initial_index: int = 0) -> str:
        """Block and wait for user selection via key presses.
        
        This is the blocking mode of operation. For non-blocking mode,
        use activate(), handle_key(), and deactivate() directly.
        
        Args:
            initial_index: Initial selection index
            
        Returns:
            Selected entry key, "BACK", "HELP", or "SHUTDOWN"
        """
        # Set initial selection
        self.set_selection(initial_index)
        
        # Activate key handling
        self.activate()
        
        try:
            log.info("IconMenuWidget: Waiting for selection...")
            self._selection_event.wait()
            result = self._selection_result or "BACK"
            log.info(f"IconMenuWidget: Selection result='{result}'")
            return result
        finally:
            self.deactivate()
    
    def cancel_selection(self, result: str = "CANCELLED") -> None:
        """Cancel the current selection wait with a custom result.
        
        This is useful for external events (like BLE connection) that need
        to interrupt the menu and trigger a specific action.
        
        Args:
            result: The result to return from wait_for_selection
        """
        self._active = False
        self._selection_result = result
        self._selection_event.set()
    
    def stop(self) -> None:
        """Stop the widget and release any blocked waits."""
        self._active = False
        self._selection_result = "BACK"
        self._selection_event.set()
        super().stop()


def create_icon_menu_entries(entries_config: List[dict]) -> List[IconMenuEntry]:
    """Helper to create IconMenuEntry list from config dictionaries.
    
    Args:
        entries_config: List of dicts with 'key', 'label', 'icon_name',
                       and optional 'enabled', 'height_ratio', 'icon_size',
                       'layout', 'font_size', 'bold'
        
    Returns:
        List of IconMenuEntry objects
    """
    return [
        IconMenuEntry(
            key=e['key'],
            label=e['label'],
            icon_name=e['icon_name'],
            enabled=e.get('enabled', True),
            height_ratio=e.get('height_ratio', 1.0),
            icon_size=e.get('icon_size', None),
            layout=e.get('layout', 'horizontal'),
            font_size=e.get('font_size', 16),
            bold=e.get('bold', False)
        )
        for e in entries_config
    ]
