"""
Chess clock service.

Manages the countdown thread and lifecycle for the chess clock.
The actual state is held in state/chess_clock.py - this service owns
the threading and control logic.

Widgets observe the state object directly, not this service.
"""

import threading
import time
from typing import Optional

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

from DGTCentaurMods.state import get_chess_clock as get_clock_state


class ChessClockService:
    """Service managing chess clock countdown thread.
    
    The service:
    - Owns the countdown thread
    - Manages clock lifecycle (start, stop, pause, resume)
    - Updates the state object which notifies observers
    
    Widgets should import from state/, not this service.
    """
    
    def __init__(self):
        """Initialize the clock service."""
        self._state = get_clock_state()
        self._lock = threading.RLock()
        
        # Initial times (for reset)
        self._initial_white_time: int = 0
        self._initial_black_time: int = 0
        
        # Countdown thread
        self._countdown_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    # -------------------------------------------------------------------------
    # Properties (delegate to state for reads)
    # -------------------------------------------------------------------------
    
    @property
    def white_time(self) -> int:
        """White's remaining time in seconds."""
        return self._state.white_time
    
    @property
    def black_time(self) -> int:
        """Black's remaining time in seconds."""
        return self._state.black_time
    
    @property
    def active_color(self) -> Optional[str]:
        """Which player's clock is active."""
        return self._state.active_color
    
    @property
    def is_running(self) -> bool:
        """Whether the clock is running."""
        return self._state.is_running
    
    @property
    def is_paused(self) -> bool:
        """Whether the clock is paused."""
        return self._state.is_paused
    
    @property
    def timed_mode(self) -> bool:
        """Whether in timed mode (countdown) vs untimed."""
        return self._state.timed_mode
    
    # -------------------------------------------------------------------------
    # Configuration methods
    # -------------------------------------------------------------------------
    
    def configure(self, time_control_minutes: int, white_name: str = "", 
                  black_name: str = "") -> None:
        """Configure the clock for a new game.
        
        Args:
            time_control_minutes: Minutes per player (0 for untimed mode)
            white_name: Optional name for white player (not stored in state)
            black_name: Optional name for black player (not stored in state)
        """
        with self._lock:
            timed = time_control_minutes > 0
            initial_seconds = time_control_minutes * 60
            
            self._initial_white_time = initial_seconds
            self._initial_black_time = initial_seconds
            
            self._state.set_timed_mode(timed)
            self._state.set_times(initial_seconds, initial_seconds)
            self._state.set_active(None)
            self._state.set_paused(False)
            self._state.set_running(False)
        
        log.info(f"[ChessClockService] Configured: {time_control_minutes} min")
    
    def set_times(self, white_seconds: int, black_seconds: int) -> None:
        """Set the remaining time for both players.
        
        Args:
            white_seconds: White's remaining time
            black_seconds: Black's remaining time
        """
        self._state.set_times(white_seconds, black_seconds)
    
    # -------------------------------------------------------------------------
    # Clock control methods
    # -------------------------------------------------------------------------
    
    def start(self, active_color: str = 'white') -> None:
        """Start the clock running.
        
        Args:
            active_color: Which player's clock starts ('white' or 'black')
        """
        with self._lock:
            self._state.set_active(active_color)
            self._state.set_paused(False)
            
            if self._state._is_running:
                # Already running
                return
            
            self._state.set_running(True)
            self._stop_event.clear()
            
            # Only start countdown thread in timed mode
            if self._state.timed_mode:
                self._countdown_thread = threading.Thread(
                    target=self._countdown_loop,
                    name="clock-service",
                    daemon=True
                )
                self._countdown_thread.start()
        
        log.info(f"[ChessClockService] Started, active: {active_color}")
    
    def pause(self) -> None:
        """Pause the clock."""
        with self._lock:
            if not self._state._is_running:
                return
            self._state.set_paused(True)
        
        log.info("[ChessClockService] Paused")
    
    def resume(self, active_color: Optional[str] = None) -> None:
        """Resume the clock after a pause.
        
        Args:
            active_color: Which player's clock resumes. If None, uses previous.
        """
        with self._lock:
            if active_color is not None:
                self._state.set_active(active_color)
            
            if not self._state._is_running:
                # Was stopped, not just paused
                color = self._state.active_color or 'white'
                self._lock.release()
                try:
                    self.start(color)
                finally:
                    self._lock.acquire()
                return
            
            self._state.set_paused(False)
        
        log.info(f"[ChessClockService] Resumed")
    
    def switch_turn(self) -> None:
        """Switch which player's clock is running."""
        current = self._state.active_color
        if current == 'white':
            self._state.set_active('black')
        elif current == 'black':
            self._state.set_active('white')
        else:
            self._state.set_active('white')
        
        log.debug(f"[ChessClockService] Switched to {self._state.active_color}")
    
    def set_active(self, color: Optional[str]) -> None:
        """Set which player's clock is active.
        
        Args:
            color: 'white', 'black', or None
        """
        self._state.set_active(color)
    
    def stop(self) -> None:
        """Stop the clock completely."""
        with self._lock:
            if not self._state._is_running:
                return
            
            self._state.set_running(False)
            self._stop_event.set()
            thread = self._countdown_thread
            self._countdown_thread = None
        
        # Join outside lock
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        
        log.info("[ChessClockService] Stopped")
    
    def reset(self) -> None:
        """Reset the clock to initial times."""
        self.stop()
        
        with self._lock:
            self._state.set_times(self._initial_white_time, self._initial_black_time)
            self._state.set_active(None)
            self._state.set_paused(False)
        
        log.info("[ChessClockService] Reset")
    
    def get_times(self) -> tuple:
        """Get the current times for both players.
        
        Returns:
            Tuple of (white_seconds, black_seconds)
        """
        return (self._state.white_time, self._state.black_time)
    
    # -------------------------------------------------------------------------
    # Internal methods
    # -------------------------------------------------------------------------
    
    def _countdown_loop(self) -> None:
        """Background thread that decrements the active player's time."""
        while not self._stop_event.is_set():
            # Wait for 1 second (interruptible)
            if self._stop_event.wait(timeout=1.0):
                break
            
            # Check if we should tick
            if not self._state._is_running or self._state._is_paused:
                continue
            
            if self._state.active_color is None:
                continue
            
            # Tick the state (decrements time, notifies observers)
            self._state.tick()


# -----------------------------------------------------------------------------
# Singleton instance
# -----------------------------------------------------------------------------

_instance: Optional[ChessClockService] = None
_lock = threading.Lock()


def get_chess_clock_service() -> ChessClockService:
    """Get the singleton ChessClockService instance.
    
    Returns:
        The global ChessClockService instance.
    """
    global _instance
    
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ChessClockService()
    
    return _instance


# Backwards compatibility alias
def get_chess_clock() -> ChessClockService:
    """Alias for get_chess_clock_service() for backwards compatibility.
    
    Note: For state access, use state.get_chess_clock() instead.
    """
    return get_chess_clock_service()
