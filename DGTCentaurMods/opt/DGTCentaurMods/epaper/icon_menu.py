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


# Default layout constants
BUTTON_MARGIN = 4
BUTTON_HEIGHT = 70


@dataclass
class IconMenuEntry:
    """Configuration for a menu entry.
    
    Attributes:
        key: Unique identifier returned on selection
        label: Display text
        icon_name: Icon identifier for rendering
        enabled: Whether entry is enabled/visible
    """
    key: str
    label: str
    icon_name: str
    enabled: bool = True


class IconMenuWidget(Widget):
    """Widget displaying a menu of large icon buttons.
    
    Displays a vertical list of icon buttons with keyboard navigation.
    Supports UP/DOWN for navigation, TICK for selection, BACK for cancel.
    
    Can be used in two modes:
    1. Callback mode: Provide on_select callback, call handle_key() externally
    2. Blocking mode: Call wait_for_selection() which blocks until user selects
    
    Attributes:
        entries: List of menu entry configurations
        selected_index: Currently highlighted entry index
    """
    
    def __init__(self, x: int, y: int, width: int, height: int,
                 entries: List[IconMenuEntry],
                 selected_index: int = 0,
                 on_select: Optional[Callable[[str], None]] = None,
                 on_back: Optional[Callable[[], None]] = None,
                 button_height: int = BUTTON_HEIGHT,
                 button_margin: int = BUTTON_MARGIN):
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
            button_height: Height of each button
            button_margin: Margin between buttons
        """
        # Use shade 2 (~12.5% grey), one up from splash screen's shade 1
        super().__init__(x, y, width, height, background_shade=2)
        
        # Filter disabled entries
        self.entries = [e for e in entries if e.enabled]
        self.selected_index = min(selected_index, max(0, len(self.entries) - 1))
        
        # Callbacks for external use
        self.on_select = on_select
        self.on_back = on_back
        
        # Layout
        self.button_height = button_height
        self.button_margin = button_margin
        
        # Selection event handling for blocking mode
        self._selection_event = threading.Event()
        self._selection_result: Optional[str] = None
        self._active = False
        
        # Create button widgets
        self._buttons: List[IconButtonWidget] = []
        self._create_buttons()
        
        log.info(f"IconMenuWidget: Created with {len(self.entries)} entries")
    
    def _create_buttons(self) -> None:
        """Create IconButtonWidget instances for each entry."""
        self._buttons = []
        
        # Calculate actual button height
        total_entries = len(self.entries)
        if total_entries == 0:
            return
        
        available_height = self.height - (self.button_margin * (total_entries + 1))
        actual_button_height = min(self.button_height, available_height // total_entries)
        button_width = self.width - (self.button_margin * 2)
        
        for idx, entry in enumerate(self.entries):
            button_y = self.button_margin + idx * (actual_button_height + self.button_margin)
            
            button = IconButtonWidget(
                x=self.button_margin,
                y=button_y,
                width=button_width,
                height=actual_button_height,
                key=entry.key,
                label=entry.label,
                icon_name=entry.icon_name,
                selected=(idx == self.selected_index)
            )
            self._buttons.append(button)
    
    def set_selection(self, index: int) -> None:
        """Set the current selection index.
        
        Args:
            index: New selection index
        """
        new_index = max(0, min(index, len(self.entries) - 1))
        if new_index != self.selected_index:
            # Update button states
            if self._buttons:
                if self.selected_index < len(self._buttons):
                    self._buttons[self.selected_index].selected = False
                if new_index < len(self._buttons):
                    self._buttons[new_index].selected = True
            
            self.selected_index = new_index
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
        
        # Render each button and paste to image
        for button in self._buttons:
            button_img = button.render()
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
        """
        self._active = True
        self._selection_result = None
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
        entries_config: List of dicts with 'key', 'label', 'icon_name', and optional 'enabled'
        
    Returns:
        List of IconMenuEntry objects
    """
    return [
        IconMenuEntry(
            key=e['key'],
            label=e['label'],
            icon_name=e['icon_name'],
            enabled=e.get('enabled', True)
        )
        for e in entries_config
    ]
