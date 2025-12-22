"""
Players state.

Holds observable player information (names, types, readiness).
UI widgets observe this state to display player information.

The actual Player objects and game logic remain in PlayerManager -
this state object provides an observable interface for the UI layer.
"""

from typing import Optional, Callable, List

from DGTCentaurMods.players.base import PlayerType


class PlayersState:
    """Observable players state.
    
    Holds:
    - Player names (white and black)
    - Player types (HUMAN, ENGINE, LICHESS)
    - Readiness state
    
    Observers are notified on:
    - Player name changes (when players are swapped)
    - Player type changes
    - Readiness changes
    
    Thread safety: Properties are simple reads. The PlayerManager that owns
    the actual players should update this state atomically.
    """
    
    def __init__(self):
        """Initialize players state with defaults."""
        # Player names
        self._white_name: str = ""
        self._black_name: str = ""
        
        # Player types
        self._white_type: PlayerType = PlayerType.HUMAN
        self._black_type: PlayerType = PlayerType.HUMAN
        
        # Readiness
        self._is_ready: bool = False
        
        # Observer callbacks
        self._on_names_change: List[Callable[[str, str], None]] = []
        self._on_types_change: List[Callable[[], None]] = []
        self._on_ready_change: List[Callable[[bool], None]] = []
    
    # -------------------------------------------------------------------------
    # Properties (read-only access to state)
    # -------------------------------------------------------------------------
    
    @property
    def white_name(self) -> str:
        """White player's display name."""
        return self._white_name
    
    @property
    def black_name(self) -> str:
        """Black player's display name."""
        return self._black_name
    
    @property
    def white_type(self) -> PlayerType:
        """White player's type (HUMAN, ENGINE, LICHESS)."""
        return self._white_type
    
    @property
    def black_type(self) -> PlayerType:
        """Black player's type (HUMAN, ENGINE, LICHESS)."""
        return self._black_type
    
    @property
    def is_two_human(self) -> bool:
        """Whether both players are human."""
        return self._white_type == PlayerType.HUMAN and self._black_type == PlayerType.HUMAN
    
    @property
    def has_engine(self) -> bool:
        """Whether either player is an engine."""
        return self._white_type == PlayerType.ENGINE or self._black_type == PlayerType.ENGINE
    
    @property
    def has_lichess(self) -> bool:
        """Whether either player is Lichess."""
        return self._white_type == PlayerType.LICHESS or self._black_type == PlayerType.LICHESS
    
    @property
    def is_ready(self) -> bool:
        """Whether all players are ready."""
        return self._is_ready
    
    # -------------------------------------------------------------------------
    # Observer management
    # -------------------------------------------------------------------------
    
    def on_names_change(self, callback: Callable[[str, str], None]) -> None:
        """Register callback for player name changes.
        
        Called when player names change (e.g., when a remote client
        takes over from the local engine).
        
        Args:
            callback: Function(white_name, black_name) called on change.
        """
        if callback not in self._on_names_change:
            self._on_names_change.append(callback)
    
    def on_types_change(self, callback: Callable[[], None]) -> None:
        """Register callback for player type changes.
        
        Args:
            callback: Function() called when player types change.
        """
        if callback not in self._on_types_change:
            self._on_types_change.append(callback)
    
    def on_ready_change(self, callback: Callable[[bool], None]) -> None:
        """Register callback for readiness changes.
        
        Args:
            callback: Function(is_ready) called when readiness changes.
        """
        if callback not in self._on_ready_change:
            self._on_ready_change.append(callback)
    
    def remove_observer(self, callback: Callable) -> None:
        """Remove a previously registered callback.
        
        Args:
            callback: The callback to remove (from any observer list).
        """
        if callback in self._on_names_change:
            self._on_names_change.remove(callback)
        if callback in self._on_types_change:
            self._on_types_change.remove(callback)
        if callback in self._on_ready_change:
            self._on_ready_change.remove(callback)
    
    def _notify_names_change(self) -> None:
        """Notify all name change observers."""
        for callback in self._on_names_change:
            try:
                callback(self._white_name, self._black_name)
            except Exception:
                pass
    
    def _notify_types_change(self) -> None:
        """Notify all type change observers."""
        for callback in self._on_types_change:
            try:
                callback()
            except Exception:
                pass
    
    def _notify_ready_change(self) -> None:
        """Notify all ready change observers."""
        for callback in self._on_ready_change:
            try:
                callback(self._is_ready)
            except Exception:
                pass
    
    # -------------------------------------------------------------------------
    # State mutations (called by PlayerManager)
    # -------------------------------------------------------------------------
    
    def set_players(self, white_name: str, black_name: str,
                    white_type: PlayerType, black_type: PlayerType) -> None:
        """Set all player information at once.
        
        Called when PlayerManager is initialized or players are swapped.
        
        Args:
            white_name: White player's display name.
            black_name: Black player's display name.
            white_type: White player's type.
            black_type: Black player's type.
        """
        names_changed = (self._white_name != white_name or 
                         self._black_name != black_name)
        types_changed = (self._white_type != white_type or 
                         self._black_type != black_type)
        
        self._white_name = white_name
        self._black_name = black_name
        self._white_type = white_type
        self._black_type = black_type
        
        if names_changed:
            self._notify_names_change()
        if types_changed:
            self._notify_types_change()
    
    def set_player_names(self, white_name: str, black_name: str) -> None:
        """Set player names only.
        
        Convenience method when only names change (e.g., player swap).
        
        Args:
            white_name: White player's display name.
            black_name: Black player's display name.
        """
        if self._white_name != white_name or self._black_name != black_name:
            self._white_name = white_name
            self._black_name = black_name
            self._notify_names_change()
    
    def set_player_types(self, white_type: PlayerType, black_type: PlayerType) -> None:
        """Set player types only.
        
        Args:
            white_type: White player's type.
            black_type: Black player's type.
        """
        if self._white_type != white_type or self._black_type != black_type:
            self._white_type = white_type
            self._black_type = black_type
            self._notify_types_change()
    
    def set_ready(self, ready: bool) -> None:
        """Set readiness state.
        
        Args:
            ready: True if all players are ready.
        """
        if self._is_ready != ready:
            self._is_ready = ready
            self._notify_ready_change()
    
    def reset(self) -> None:
        """Reset to initial state.
        
        Called when a game ends or is cleaned up.
        """
        self._white_name = ""
        self._black_name = ""
        self._white_type = PlayerType.HUMAN
        self._black_type = PlayerType.HUMAN
        self._is_ready = False
        self._notify_names_change()
        self._notify_types_change()
        self._notify_ready_change()


# -----------------------------------------------------------------------------
# Singleton instance
# -----------------------------------------------------------------------------

_instance: Optional[PlayersState] = None


def get_players_state() -> PlayersState:
    """Get the singleton PlayersState instance.
    
    Returns:
        The global PlayersState instance.
    """
    global _instance
    if _instance is None:
        _instance = PlayersState()
    return _instance


def reset_players_state() -> PlayersState:
    """Reset the singleton to a fresh instance.
    
    Primarily for testing.
    
    Returns:
        The new PlayersState instance.
    """
    global _instance
    _instance = PlayersState()
    return _instance
