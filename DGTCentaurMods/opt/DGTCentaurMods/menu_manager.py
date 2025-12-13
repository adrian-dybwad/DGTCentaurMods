"""Menu manager for managing menu navigation and state.

Provides a centralized manager for menu navigation that:
- Handles break results (CLIENT_CONNECTED, PIECE_MOVED) automatically
- Manages menu state and navigation
- Simplifies menu handler code by removing boilerplate

The MenuManager is a singleton that manages the active menu widget
and provides a clean API for showing menus and handling results.
"""

import logging
from enum import Enum, auto
from typing import List, Callable, Optional, Any, Union
from dataclasses import dataclass

from DGTCentaurMods.epaper.icon_menu import IconMenuEntry, IconMenuWidget

log = logging.getLogger(__name__)


class MenuResult(Enum):
    """Standard menu result types."""
    BACK = auto()           # User pressed back
    SHUTDOWN = auto()       # Shutdown requested
    HELP = auto()           # Help requested
    CLIENT_CONNECTED = auto()  # BLE/RFCOMM client connected
    PIECE_MOVED = auto()    # Piece moved on board
    

# Result strings that map to MenuResult enum
RESULT_MAP = {
    "BACK": MenuResult.BACK,
    "SHUTDOWN": MenuResult.SHUTDOWN,
    "HELP": MenuResult.HELP,
    "CLIENT_CONNECTED": MenuResult.CLIENT_CONNECTED,
    "PIECE_MOVED": MenuResult.PIECE_MOVED,
}

# Results that should break out of all nested menus
BREAK_RESULTS = {MenuResult.CLIENT_CONNECTED, MenuResult.PIECE_MOVED}


@dataclass
class MenuSelection:
    """Result of a menu selection.
    
    Attributes:
        key: The key of the selected entry (string)
        result_type: Standard result type if applicable (MenuResult enum or None)
        is_break: True if this result should break out of all nested menus
    """
    key: str
    result_type: Optional[MenuResult] = None
    is_break: bool = False
    
    @classmethod
    def from_key(cls, key: str) -> 'MenuSelection':
        """Create MenuSelection from a key string."""
        result_type = RESULT_MAP.get(key)
        is_break = result_type in BREAK_RESULTS if result_type else False
        return cls(key=key, result_type=result_type, is_break=is_break)
    
    def is_back(self) -> bool:
        """Check if this is a BACK result."""
        return self.result_type == MenuResult.BACK
    
    def is_exit(self) -> bool:
        """Check if this result should exit the current menu (BACK, SHUTDOWN, HELP, or break)."""
        return self.is_break or self.result_type in {MenuResult.BACK, MenuResult.SHUTDOWN, MenuResult.HELP}


class MenuManager:
    """Manager for menu navigation and state.
    
    Singleton class that provides centralized menu management.
    Handles the active menu widget, break results, and state transitions.
    
    Usage:
        manager = MenuManager.get_instance()
        
        # Simple menu display
        result = manager.show_menu(entries)
        if result.is_break:
            return result  # Propagate break to caller
        if result.is_back():
            return  # Exit this menu level
            
        # Handle specific selections
        if result.key == "SomeOption":
            handle_some_option()
    """
    
    _instance: Optional['MenuManager'] = None
    
    def __init__(self):
        """Initialize the menu manager."""
        self._active_widget: Optional[IconMenuWidget] = None
        self._board = None  # Set via set_board()
        self._status_bar_height = 16  # Default, can be overridden
        self._display_width = 128
        self._display_height = 296
    
    @classmethod
    def get_instance(cls) -> 'MenuManager':
        """Get the singleton instance of MenuManager."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def set_board(self, board):
        """Set the board module reference.
        
        Args:
            board: The board module for display management
        """
        self._board = board
    
    def set_dimensions(self, width: int, height: int, status_bar_height: int = 16):
        """Set display dimensions.
        
        Args:
            width: Display width in pixels
            height: Display height in pixels  
            status_bar_height: Height of status bar in pixels
        """
        self._display_width = width
        self._display_height = height
        self._status_bar_height = status_bar_height
    
    @property
    def active_widget(self) -> Optional[IconMenuWidget]:
        """Get the currently active menu widget."""
        return self._active_widget
    
    def cancel_selection(self, result: str):
        """Cancel the current menu with a specific result.
        
        Used to interrupt menus when external events occur (BLE connection, etc.)
        
        Args:
            result: Result string to return from the menu
        """
        if self._active_widget is not None:
            log.info(f"[MenuManager] Cancelling menu with result: {result}")
            self._active_widget.cancel_selection(result)
    
    def show_menu(
        self,
        entries: List[IconMenuEntry],
        initial_index: int = 0
    ) -> MenuSelection:
        """Display a menu and wait for selection.
        
        This is the primary method for showing menus. It handles:
        - Creating and displaying the menu widget
        - Managing the active widget state
        - Converting the result to a MenuSelection object
        
        Args:
            entries: List of menu entry configurations
            initial_index: Index of entry to select initially
            
        Returns:
            MenuSelection with the user's selection or break result
        """
        if self._board is None:
            raise RuntimeError("MenuManager.set_board() must be called before show_menu()")
        
        # Create menu widget
        menu_widget = IconMenuWidget(
            x=0,
            y=self._status_bar_height,
            width=self._display_width,
            height=self._display_height - self._status_bar_height,
            entries=entries,
            selected_index=initial_index
        )
        
        # Register as active menu
        self._active_widget = menu_widget
        
        # Add widget to display
        promise = self._board.display_manager.add_widget(menu_widget)
        if promise:
            try:
                promise.result(timeout=5.0)
            except Exception as e:
                log.warning(f"[MenuManager] Error waiting for menu render: {e}")
        
        try:
            # Wait for selection
            result_key = menu_widget.wait_for_selection(initial_index=initial_index)
            return MenuSelection.from_key(result_key)
        finally:
            self._active_widget = None
    
    def run_menu_loop(
        self,
        build_entries: Callable[[], List[IconMenuEntry]],
        handle_selection: Callable[[MenuSelection], Optional[MenuSelection]],
        initial_index: int = 0,
        track_selection: bool = True
    ) -> Optional[MenuSelection]:
        """Run a menu loop with automatic break handling.
        
        Simplifies the common pattern of:
        - Build entries
        - Show menu
        - Check for breaks/back
        - Handle selection
        - Loop
        
        Args:
            build_entries: Function that returns the menu entries (called each iteration)
            handle_selection: Function to handle the selection. Should return:
                             - None to continue the loop
                             - MenuSelection to exit (propagates breaks/back)
            initial_index: Starting selection index
            track_selection: If True, tracks last selection and uses it on next iteration
            
        Returns:
            MenuSelection if exited due to break/back, None if handle_selection returned
        """
        last_index = initial_index
        
        while True:
            entries = build_entries()
            result = self.show_menu(entries, initial_index=last_index)
            
            # Always propagate break results
            if result.is_break:
                return result
            
            # Update tracked index
            if track_selection:
                last_index = self._find_entry_index(entries, result.key)
            
            # Exit on standard exit results
            if result.result_type in {MenuResult.BACK, MenuResult.SHUTDOWN, MenuResult.HELP}:
                return result
            
            # Let handler process the selection
            handler_result = handle_selection(result)
            if handler_result is not None:
                return handler_result
    
    def _find_entry_index(self, entries: List[IconMenuEntry], key: str) -> int:
        """Find the index of an entry by its key.
        
        Args:
            entries: List of menu entries
            key: Key to search for
            
        Returns:
            Index of matching entry, or 0 if not found
        """
        for i, entry in enumerate(entries):
            if entry.key == key:
                return i
        return 0


def is_break_result(result: Union[str, MenuSelection, None]) -> bool:
    """Check if a result should break out of all nested menus.
    
    Utility function for checking results without MenuManager.
    
    Args:
        result: String key, MenuSelection, or None
        
    Returns:
        True if this is a break result, False if None or not a break result
    """
    if result is None:
        return False
    if isinstance(result, MenuSelection):
        return result.is_break
    return result in {"CLIENT_CONNECTED", "PIECE_MOVED"}


def find_entry_index(entries: List[IconMenuEntry], key: str) -> int:
    """Find the index of an entry by its key.
    
    Utility function for finding entry indices.
    
    Args:
        entries: List of menu entries
        key: Key to search for
        
    Returns:
        Index of matching entry, or 0 if not found
    """
    for i, entry in enumerate(entries):
        if entry.key == key:
            return i
    return 0
