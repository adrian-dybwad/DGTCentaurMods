"""
Chess clock.

Manages chess clock state and countdown timer independently of UI widgets.
The ChessClock persists across widget creation/destruction (e.g., when menus
are shown), ensuring consistent time tracking.

The ChessClockWidget observes this clock to display the current state.

Responsibilities:
- Track remaining time for both players (in seconds)
- Track which player's clock is currently running
- Run background countdown thread when active
- Emit callbacks when time changes or expires (flag)
- Provide thread-safe access to clock state
"""

import threading
import time
from typing import Optional, Callable, List

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class ChessClock:
    """
    Chess clock managing state and countdown.
    
    Provides a stable clock that persists across UI changes. Widgets observe
    this clock rather than managing their own timers.
    
    Supports:
    - Timed mode: countdown from initial time, switch on moves
    - Untimed mode: just track whose turn it is (no countdown)
    
    Thread safety: All public methods are thread-safe. State changes are
    protected by a lock. Callbacks are invoked outside the lock to prevent
    deadlocks.
    """
    
    def __init__(self):
        """Initialize the clock service in stopped state."""
        self._lock = threading.RLock()
        
        # Time state (in seconds)
        self._white_time: int = 0
        self._black_time: int = 0
        self._initial_white_time: int = 0
        self._initial_black_time: int = 0
        
        # Active player
        self._active_color: Optional[str] = None  # None, 'white', or 'black'
        
        # Running state
        self._is_running: bool = False
        self._is_paused: bool = False
        self._timed_mode: bool = False
        
        # Player names
        self._white_name: str = ""
        self._black_name: str = ""
        
        # Countdown thread
        self._countdown_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Callbacks
        self._on_tick_callbacks: List[Callable[[], None]] = []
        self._on_flag_callbacks: List[Callable[[str], None]] = []
        self._on_state_change_callbacks: List[Callable[[], None]] = []
    
    # -------------------------------------------------------------------------
    # Properties (read-only access to state)
    # -------------------------------------------------------------------------
    
    @property
    def white_time(self) -> int:
        """White's remaining time in seconds."""
        with self._lock:
            return self._white_time
    
    @property
    def black_time(self) -> int:
        """Black's remaining time in seconds."""
        with self._lock:
            return self._black_time
    
    @property
    def active_color(self) -> Optional[str]:
        """Which player's clock is active ('white', 'black', or None)."""
        with self._lock:
            return self._active_color
    
    @property
    def is_running(self) -> bool:
        """Whether the clock countdown is currently running."""
        with self._lock:
            return self._is_running and not self._is_paused
    
    @property
    def is_paused(self) -> bool:
        """Whether the clock is paused (thread running but not decrementing)."""
        with self._lock:
            return self._is_paused
    
    @property
    def timed_mode(self) -> bool:
        """Whether the clock is in timed mode (countdown) vs untimed (turn only)."""
        with self._lock:
            return self._timed_mode
    
    @property
    def white_name(self) -> str:
        """White player's name."""
        with self._lock:
            return self._white_name
    
    @property
    def black_name(self) -> str:
        """Black player's name."""
        with self._lock:
            return self._black_name
    
    # -------------------------------------------------------------------------
    # Configuration methods
    # -------------------------------------------------------------------------
    
    def configure(self, time_control_minutes: int, white_name: str = "", 
                  black_name: str = "") -> None:
        """Configure the clock for a new game.
        
        Sets up initial times and player names. Does not start the clock.
        
        Args:
            time_control_minutes: Minutes per player (0 for untimed mode)
            white_name: Optional name for white player
            black_name: Optional name for black player
        """
        with self._lock:
            self._timed_mode = time_control_minutes > 0
            initial_seconds = time_control_minutes * 60
            self._white_time = initial_seconds
            self._black_time = initial_seconds
            self._initial_white_time = initial_seconds
            self._initial_black_time = initial_seconds
            self._white_name = white_name
            self._black_name = black_name
            self._active_color = None
            self._is_paused = False
        
        self._notify_state_change()
        log.info(f"[ChessClock] Configured: {time_control_minutes} min, "
                 f"white='{white_name}', black='{black_name}'")
    
    def set_times(self, white_seconds: int, black_seconds: int) -> None:
        """Set the remaining time for both players.
        
        Args:
            white_seconds: White's remaining time in seconds
            black_seconds: Black's remaining time in seconds
        """
        with self._lock:
            self._white_time = white_seconds
            self._black_time = black_seconds
        
        self._notify_state_change()
    
    def set_player_names(self, white_name: str, black_name: str) -> None:
        """Set player names.
        
        Args:
            white_name: White player's name
            black_name: Black player's name
        """
        with self._lock:
            self._white_name = white_name
            self._black_name = black_name
        
        self._notify_state_change()
    
    # -------------------------------------------------------------------------
    # Clock control methods
    # -------------------------------------------------------------------------
    
    def start(self, active_color: str = 'white') -> None:
        """Start the clock running.
        
        Starts the countdown thread if not already running. In untimed mode,
        just sets the active color without starting countdown.
        
        Args:
            active_color: Which player's clock starts running ('white' or 'black')
        """
        with self._lock:
            self._active_color = active_color
            self._is_paused = False
            
            if self._is_running:
                # Already running - just update active color
                self._notify_state_change()
                return
            
            self._is_running = True
            self._stop_event.clear()
            
            # Only start countdown thread in timed mode
            if self._timed_mode:
                self._countdown_thread = threading.Thread(
                    target=self._countdown_loop,
                    name="clock-service",
                    daemon=True
                )
                self._countdown_thread.start()
        
        self._notify_state_change()
        log.info(f"[ChessClock] Started, active: {active_color}, timed: {self._timed_mode}")
    
    def pause(self) -> None:
        """Pause the clock (time stops but thread continues).
        
        The clock can be resumed with resume(). The active color is remembered.
        """
        with self._lock:
            if not self._is_running:
                return
            self._is_paused = True
        
        self._notify_state_change()
        log.info("[ChessClock] Paused")
    
    def resume(self, active_color: Optional[str] = None) -> None:
        """Resume the clock after a pause.
        
        Args:
            active_color: Which player's clock resumes. If None, uses the
                         color that was active when paused.
        """
        with self._lock:
            if active_color is not None:
                self._active_color = active_color
            
            if not self._is_running:
                # Was stopped, not just paused - start fresh
                color = self._active_color or 'white'
                self._lock.release()
                try:
                    self.start(color)
                finally:
                    self._lock.acquire()
                return
            
            self._is_paused = False
        
        self._notify_state_change()
        log.info(f"[ChessClock] Resumed, active: {self._active_color}")
    
    def switch_turn(self) -> None:
        """Switch which player's clock is running.
        
        If no player is active, defaults to white.
        """
        with self._lock:
            if self._active_color == 'white':
                self._active_color = 'black'
            elif self._active_color == 'black':
                self._active_color = 'white'
            else:
                self._active_color = 'white'
        
        self._notify_state_change()
        log.debug(f"[ChessClock] Switched to {self._active_color}")
    
    def set_active(self, color: Optional[str]) -> None:
        """Set which player's clock is active.
        
        Args:
            color: 'white', 'black', or None (both stopped)
        """
        with self._lock:
            self._active_color = color
        
        self._notify_state_change()
    
    def stop(self) -> None:
        """Stop the clock completely.
        
        Stops the countdown thread. Use start() to begin a new session.
        """
        with self._lock:
            if not self._is_running:
                return
            
            self._is_running = False
            self._stop_event.set()
            thread = self._countdown_thread
            self._countdown_thread = None
        
        # Join outside lock to prevent deadlock
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        
        self._notify_state_change()
        log.info("[ChessClock] Stopped")
    
    def reset(self) -> None:
        """Reset the clock to initial times.
        
        Stops the clock and resets times to the values set in configure().
        """
        self.stop()
        
        with self._lock:
            self._white_time = self._initial_white_time
            self._black_time = self._initial_black_time
            self._active_color = None
            self._is_paused = False
        
        self._notify_state_change()
        log.info("[ChessClock] Reset to initial times")
    
    def get_times(self) -> tuple[int, int]:
        """Get the current times for both players.
        
        Returns:
            Tuple of (white_seconds, black_seconds)
        """
        with self._lock:
            return (self._white_time, self._black_time)
    
    # -------------------------------------------------------------------------
    # Callback registration
    # -------------------------------------------------------------------------
    
    def on_tick(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked every second when clock is running.
        
        Args:
            callback: Function called with no arguments on each tick
        """
        with self._lock:
            self._on_tick_callbacks.append(callback)
    
    def on_flag(self, callback: Callable[[str], None]) -> None:
        """Register a callback invoked when a player's time expires.
        
        Args:
            callback: Function called with the color ('white' or 'black') that flagged
        """
        with self._lock:
            self._on_flag_callbacks.append(callback)
    
    def on_state_change(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked when any clock state changes.
        
        This includes time changes, active player changes, start/stop, etc.
        Widgets should use this to know when to re-render.
        
        Args:
            callback: Function called with no arguments on state change
        """
        with self._lock:
            self._on_state_change_callbacks.append(callback)
    
    def remove_callback(self, callback: Callable) -> None:
        """Remove a previously registered callback.
        
        Args:
            callback: The callback function to remove
        """
        with self._lock:
            if callback in self._on_tick_callbacks:
                self._on_tick_callbacks.remove(callback)
            if callback in self._on_flag_callbacks:
                self._on_flag_callbacks.remove(callback)
            if callback in self._on_state_change_callbacks:
                self._on_state_change_callbacks.remove(callback)
    
    # -------------------------------------------------------------------------
    # Internal methods
    # -------------------------------------------------------------------------
    
    def _countdown_loop(self) -> None:
        """Background thread that decrements the active player's time."""
        last_tick = time.monotonic()
        
        while not self._stop_event.is_set():
            # Wait for 1 second (interruptible)
            if self._stop_event.wait(timeout=1.0):
                break
            
            # Check state
            with self._lock:
                if not self._is_running or self._is_paused:
                    continue
                
                active = self._active_color
                if active is None:
                    continue
            
            # Calculate elapsed time
            now = time.monotonic()
            elapsed = int(now - last_tick)
            last_tick = now
            
            if elapsed <= 0:
                continue
            
            # Decrement and check for flag
            flagged_color = None
            with self._lock:
                if self._active_color == 'white' and self._white_time > 0:
                    self._white_time = max(0, self._white_time - elapsed)
                    if self._white_time == 0:
                        flagged_color = 'white'
                elif self._active_color == 'black' and self._black_time > 0:
                    self._black_time = max(0, self._black_time - elapsed)
                    if self._black_time == 0:
                        flagged_color = 'black'
            
            # Notify tick (outside lock)
            self._notify_tick()
            
            # Notify flag if time expired (outside lock)
            if flagged_color:
                log.info(f"[ChessClock] {flagged_color.capitalize()} flagged!")
                self._notify_flag(flagged_color)
    
    def _notify_tick(self) -> None:
        """Notify all tick callbacks."""
        with self._lock:
            callbacks = self._on_tick_callbacks.copy()
        
        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                log.error(f"[ChessClock] Error in tick callback: {e}")
    
    def _notify_flag(self, color: str) -> None:
        """Notify all flag callbacks."""
        with self._lock:
            callbacks = self._on_flag_callbacks.copy()
        
        for callback in callbacks:
            try:
                callback(color)
            except Exception as e:
                log.error(f"[ChessClock] Error in flag callback: {e}")
    
    def _notify_state_change(self) -> None:
        """Notify all state change callbacks."""
        with self._lock:
            callbacks = self._on_state_change_callbacks.copy()
        
        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                log.error(f"[ChessClock] Error in state change callback: {e}")


# -----------------------------------------------------------------------------
# Singleton instance
# -----------------------------------------------------------------------------

_chess_clock: Optional[ChessClock] = None
_chess_clock_lock = threading.Lock()


def get_chess_clock() -> ChessClock:
    """Get the singleton ChessClock instance.
    
    Creates the instance on first call. Thread-safe.
    
    Returns:
        The global ChessClock instance
    """
    global _chess_clock
    
    if _chess_clock is None:
        with _chess_clock_lock:
            if _chess_clock is None:
                _chess_clock = ChessClock()
    
    return _chess_clock
