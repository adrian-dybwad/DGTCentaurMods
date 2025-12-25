"""
Chromecast connection state.

Holds the current streaming state, device name, and error information.
The actual connection management is handled by the chromecast service.

Widgets observe this state to display connection status indicators.
"""

from typing import Optional, Callable, List


# Streaming states
STATE_IDLE = 0
STATE_CONNECTING = 1
STATE_STREAMING = 2
STATE_RECONNECTING = 3
STATE_ERROR = 4


class ChromecastState:
    """Observable Chromecast connection state.
    
    Holds:
    - Current streaming state (idle, connecting, streaming, etc.)
    - Device name when connected
    - Error message if in error state
    
    Observers are notified on any state change.
    """
    
    def __init__(self):
        """Initialize in idle state."""
        self._state: int = STATE_IDLE
        self._device_name: Optional[str] = None
        self._error_message: Optional[str] = None
        
        # Observer callbacks
        self._observers: List[Callable[[], None]] = []
    
    # -------------------------------------------------------------------------
    # Properties (read-only access to state)
    # -------------------------------------------------------------------------
    
    @property
    def state(self) -> int:
        """Current streaming state (STATE_IDLE, STATE_STREAMING, etc.)."""
        return self._state
    
    @property
    def device_name(self) -> Optional[str]:
        """Name of the connected Chromecast device, or None."""
        return self._device_name
    
    @property
    def error_message(self) -> Optional[str]:
        """Error message if in error state, or None."""
        return self._error_message
    
    @property
    def is_active(self) -> bool:
        """True if streaming or attempting to stream."""
        return self._state in (STATE_CONNECTING, STATE_STREAMING, STATE_RECONNECTING)
    
    @property
    def is_streaming(self) -> bool:
        """True if actively streaming."""
        return self._state == STATE_STREAMING
    
    @property
    def is_idle(self) -> bool:
        """True if not connected and not trying to connect."""
        return self._state == STATE_IDLE
    
    @property
    def is_error(self) -> bool:
        """True if in error state."""
        return self._state == STATE_ERROR
    
    # -------------------------------------------------------------------------
    # Observer management
    # -------------------------------------------------------------------------
    
    def add_observer(self, callback: Callable[[], None]) -> None:
        """Register callback for state changes.
        
        Args:
            callback: Function with no arguments, called on state change.
        """
        if callback not in self._observers:
            self._observers.append(callback)
    
    def remove_observer(self, callback: Callable[[], None]) -> None:
        """Remove a previously registered callback.
        
        Args:
            callback: The callback to remove.
        """
        if callback in self._observers:
            self._observers.remove(callback)
    
    def _notify(self) -> None:
        """Notify all observers of state change."""
        for callback in self._observers:
            try:
                callback()
            except Exception:
                pass
    
    # -------------------------------------------------------------------------
    # State mutations (called by chromecast service)
    # -------------------------------------------------------------------------
    
    def set_idle(self) -> None:
        """Set state to idle (disconnected)."""
        self._state = STATE_IDLE
        self._device_name = None
        self._error_message = None
        self._notify()
    
    def set_connecting(self, device_name: str) -> None:
        """Set state to connecting.
        
        Args:
            device_name: Name of the device being connected to.
        """
        self._state = STATE_CONNECTING
        self._device_name = device_name
        self._error_message = None
        self._notify()
    
    def set_streaming(self, device_name: str) -> None:
        """Set state to actively streaming.
        
        Args:
            device_name: Name of the connected device.
        """
        self._state = STATE_STREAMING
        self._device_name = device_name
        self._error_message = None
        self._notify()
    
    def set_reconnecting(self) -> None:
        """Set state to reconnecting (lost connection, trying to restore)."""
        self._state = STATE_RECONNECTING
        self._error_message = None
        self._notify()
    
    def set_error(self, message: str) -> None:
        """Set state to error.
        
        Args:
            message: Error description.
        """
        self._state = STATE_ERROR
        self._error_message = message
        self._notify()


# -----------------------------------------------------------------------------
# Singleton instance
# -----------------------------------------------------------------------------

_instance: Optional[ChromecastState] = None


def get_chromecast() -> ChromecastState:
    """Get the singleton ChromecastState instance.
    
    Returns:
        The global ChromecastState instance.
    """
    global _instance
    if _instance is None:
        _instance = ChromecastState()
    return _instance


def reset_chromecast() -> ChromecastState:
    """Reset the singleton to a fresh instance.
    
    Primarily for testing.
    
    Returns:
        The new ChromecastState instance.
    """
    global _instance
    _instance = ChromecastState()
    return _instance
