"""
Chess clock state.

Holds clock times and active player state. The countdown thread is managed
by the clock service - this is just the observable state.

Widgets observe this state to display times and active player indicator.
"""

from typing import Optional, Callable, List


class ChessClockState:
    """Observable chess clock state.
    
    Holds:
    - Remaining time for each player (in seconds)
    - Which player's clock is active
    - Whether clock is running/paused
    - Timed vs untimed mode
    
    Observers are notified on:
    - Tick (every second when running)
    - State changes (start, pause, resume, switch turn)
    - Flag (time expired)
    
    Thread safety: Properties are simple reads, but the service that owns
    this state should use a lock when mutating multiple fields atomically.
    """
    
    def __init__(self):
        """Initialize clock state in stopped state."""
        # Time state (in seconds)
        self._white_time: int = 0
        self._black_time: int = 0
        
        # Active player
        self._active_color: Optional[str] = None  # None, 'white', or 'black'
        
        # Running state
        self._is_running: bool = False
        self._is_paused: bool = False
        self._timed_mode: bool = False
        
        # Observer callbacks
        self._on_tick: List[Callable[[], None]] = []
        self._on_state_change: List[Callable[[], None]] = []
        self._on_flag: List[Callable[[str], None]] = []  # color that flagged
    
    # -------------------------------------------------------------------------
    # Properties (read-only access to state)
    # -------------------------------------------------------------------------
    
    @property
    def white_time(self) -> int:
        """White's remaining time in seconds."""
        return self._white_time
    
    @property
    def black_time(self) -> int:
        """Black's remaining time in seconds."""
        return self._black_time
    
    @property
    def active_color(self) -> Optional[str]:
        """Which player's clock is active ('white', 'black', or None)."""
        return self._active_color
    
    @property
    def is_running(self) -> bool:
        """Whether the clock countdown is currently running."""
        return self._is_running and not self._is_paused
    
    @property
    def is_paused(self) -> bool:
        """Whether the clock is paused (active but not counting down)."""
        return self._is_paused
    
    @property
    def timed_mode(self) -> bool:
        """Whether clock is in timed mode (countdown) vs untimed (turn indicator only)."""
        return self._timed_mode
    
    # -------------------------------------------------------------------------
    # Observer management
    # -------------------------------------------------------------------------
    
    def on_tick(self, callback: Callable[[], None]) -> None:
        """Register callback for tick events (every second when running).
        
        Args:
            callback: Function with no arguments, called each tick.
        """
        if callback not in self._on_tick:
            self._on_tick.append(callback)
    
    def on_state_change(self, callback: Callable[[], None]) -> None:
        """Register callback for state changes (start, pause, switch, etc.).
        
        Args:
            callback: Function with no arguments, called on state change.
        """
        if callback not in self._on_state_change:
            self._on_state_change.append(callback)
    
    def on_flag(self, callback: Callable[[str], None]) -> None:
        """Register callback for flag events (time expired).
        
        Args:
            callback: Function(color) called when a player's time expires.
        """
        if callback not in self._on_flag:
            self._on_flag.append(callback)
    
    def remove_observer(self, callback: Callable) -> None:
        """Remove a previously registered callback.
        
        Args:
            callback: The callback to remove (from any observer list).
        """
        if callback in self._on_tick:
            self._on_tick.remove(callback)
        if callback in self._on_state_change:
            self._on_state_change.remove(callback)
        if callback in self._on_flag:
            self._on_flag.remove(callback)
    
    def _notify_tick(self) -> None:
        """Notify all tick observers."""
        for callback in self._on_tick:
            try:
                callback()
            except Exception:
                pass
    
    def _notify_state_change(self) -> None:
        """Notify all state change observers."""
        for callback in self._on_state_change:
            try:
                callback()
            except Exception:
                pass
    
    def _notify_flag(self, color: str) -> None:
        """Notify all flag observers."""
        for callback in self._on_flag:
            try:
                callback(color)
            except Exception:
                pass
    
    # -------------------------------------------------------------------------
    # State mutations (called by clock service)
    # -------------------------------------------------------------------------
    
    def set_times(self, white_seconds: int, black_seconds: int) -> None:
        """Set remaining times for both players.
        
        Args:
            white_seconds: White's remaining time in seconds.
            black_seconds: Black's remaining time in seconds.
        """
        self._white_time = white_seconds
        self._black_time = black_seconds
        self._notify_state_change()
    
    def set_active(self, color: Optional[str]) -> None:
        """Set which player's clock is active.
        
        Args:
            color: 'white', 'black', or None.
        """
        self._active_color = color
        self._notify_state_change()
    
    def set_running(self, running: bool) -> None:
        """Set running state.
        
        Args:
            running: True if clock should be running.
        """
        self._is_running = running
        self._notify_state_change()
    
    def set_paused(self, paused: bool) -> None:
        """Set paused state.
        
        Args:
            paused: True if clock should be paused.
        """
        self._is_paused = paused
        self._notify_state_change()
    
    def set_timed_mode(self, timed: bool) -> None:
        """Set timed mode.
        
        Args:
            timed: True for countdown mode, False for turn indicator only.
        """
        self._timed_mode = timed
        self._notify_state_change()
    
    def tick(self) -> None:
        """Decrement active player's time by one second.
        
        Called by the clock service's countdown thread.
        Notifies tick observers and checks for flag.
        """
        if self._active_color == 'white':
            self._white_time = max(0, self._white_time - 1)
            if self._white_time == 0:
                self._notify_flag('white')
        elif self._active_color == 'black':
            self._black_time = max(0, self._black_time - 1)
            if self._black_time == 0:
                self._notify_flag('black')
        
        self._notify_tick()
    
    def reset(self) -> None:
        """Reset clock to initial stopped state."""
        self._white_time = 0
        self._black_time = 0
        self._active_color = None
        self._is_running = False
        self._is_paused = False
        self._timed_mode = False
        self._notify_state_change()


# -----------------------------------------------------------------------------
# Singleton instance
# -----------------------------------------------------------------------------

_instance: Optional[ChessClockState] = None


def get_chess_clock() -> ChessClockState:
    """Get the singleton ChessClockState instance.
    
    Returns:
        The global ChessClockState instance.
    """
    global _instance
    if _instance is None:
        _instance = ChessClockState()
    return _instance


def reset_chess_clock() -> ChessClockState:
    """Reset the singleton to a fresh instance.
    
    Primarily for testing.
    
    Returns:
        The new ChessClockState instance.
    """
    global _instance
    _instance = ChessClockState()
    return _instance
