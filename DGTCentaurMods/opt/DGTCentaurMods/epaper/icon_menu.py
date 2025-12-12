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
    """
    key: str
    label: str
    icon_name: str
    enabled: bool = True
    height_ratio: float = 1.0
    icon_size: int = None
    layout: str = "horizontal"
    font_size: int = 16


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
                 button_height: int = 70,
                 button_margin: int = 4,
                 background_shade: int = 2):
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
        
        # Selection event handling for blocking mode
        self._selection_event = threading.Event()
        self._selection_result: Optional[str] = None
        self._active = False
        
        # Create button widgets
        self._buttons: List[IconButtonWidget] = []
        self._create_buttons()
        
        log.info(f"IconMenuWidget: Created with {len(self.entries)} entries")
    
    def _create_buttons(self) -> None:
        """Create IconButtonWidget instances for each entry.
        
        Buttons are placed directly adjacent to each other. Each button
        has its own transparent margin (set to button_margin), so the
        visual spacing between buttons is automatic.
        
        Button heights are proportional to their height_ratio values.
        For example, if entries have ratios [2.0, 1.0, 0.67], the first
        button gets 2/(2+1+0.67) of the total height.
        """
        self._buttons = []
        
        total_entries = len(self.entries)
        if total_entries == 0:
            return
        
        # Calculate total height ratio and individual button heights
        total_ratio = sum(entry.height_ratio for entry in self.entries)
        available_height = self.height
        
        current_y = 0
        for idx, entry in enumerate(self.entries):
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
                selected=(idx == self.selected_index),
                margin=self.button_margin,
                icon_size=icon_size,
                layout=entry.layout,
                font_size=entry.font_size
            )
            self._buttons.append(button)
            current_y += button_height
    
    def set_selection(self, index: int) -> None:
        """Set the current selection index.
        
        Args:
            index: New selection index
        """
        new_index = max(0, min(index, len(self.entries) - 1))
        if new_index != self.selected_index:
            # Update button states using setter methods
            if self._buttons:
                if self.selected_index < len(self._buttons):
                    self._buttons[self.selected_index].set_selected(False)
                if new_index < len(self._buttons):
                    self._buttons[new_index].set_selected(True)
            
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
        entries_config: List of dicts with 'key', 'label', 'icon_name', 
                       and optional 'enabled', 'height_ratio', 'icon_size',
                       'layout', 'font_size'
        
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
            font_size=e.get('font_size', 16)
        )
        for e in entries_config
    ]
