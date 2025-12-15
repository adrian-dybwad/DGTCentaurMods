"""
Chromecast streaming service.

Manages the Chromecast connection and streaming lifecycle independently of UI.
Widgets observe this service's state to display status indicators.

The service persists its streaming state to a file so it can resume streaming
after an app restart.
"""

import threading
import time
import os
import json
from typing import Optional, Callable, List

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

# State file for persisting streaming state across restarts
STATE_FILE = "/tmp/dgtcm-chromecast-state.json"


class ChromecastService:
    """Singleton service managing Chromecast streaming.
    
    The service handles:
    - Device discovery
    - Connection management
    - Stream monitoring and auto-reconnect
    - State notifications to observers
    
    Observers are notified when state changes so widgets can update their display.
    """
    
    # Streaming states
    STATE_IDLE = 0
    STATE_CONNECTING = 1
    STATE_STREAMING = 2
    STATE_RECONNECTING = 3
    STATE_ERROR = 4
    
    def __init__(self):
        self._state = self.STATE_IDLE
        self._device_name: Optional[str] = None
        self._error_message: Optional[str] = None
        
        # Thread management
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        
        # pychromecast objects (lazy loaded)
        self._chromecast = None
        self._browser = None
        
        # Observers to notify on state change
        self._observers: List[Callable[[], None]] = []
        self._lock = threading.Lock()
        
        # Check for persisted state and resume streaming if needed
        self._restore_state()
    
    def _save_state(self) -> None:
        """Persist current streaming state to file.
        
        Saves device name when streaming is active, clears file when stopped.
        """
        try:
            if self.is_active and self._device_name:
                state = {"device_name": self._device_name}
                with open(STATE_FILE, "w") as f:
                    json.dump(state, f)
                log.debug(f"[ChromecastService] Saved state: {self._device_name}")
            else:
                # Clear state file when not streaming
                if os.path.exists(STATE_FILE):
                    os.remove(STATE_FILE)
                    log.debug("[ChromecastService] Cleared state file")
        except Exception as e:
            log.debug(f"[ChromecastService] Error saving state: {e}")
    
    def _restore_state(self) -> None:
        """Restore streaming state from file and resume if previously active.
        
        Called on service initialization to resume streaming after app restart.
        """
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
                device_name = state.get("device_name")
                if device_name:
                    log.info(f"[ChromecastService] Restoring stream to: {device_name}")
                    # Start streaming in background (don't block init)
                    self.start_streaming(device_name)
        except Exception as e:
            log.debug(f"[ChromecastService] Error restoring state: {e}")
    
    @property
    def state(self) -> int:
        """Current streaming state."""
        return self._state
    
    @property
    def device_name(self) -> Optional[str]:
        """Name of the connected Chromecast device."""
        return self._device_name
    
    @property
    def error_message(self) -> Optional[str]:
        """Error message if in error state."""
        return self._error_message
    
    @property
    def is_active(self) -> bool:
        """True if streaming or attempting to stream."""
        return self._state in (self.STATE_CONNECTING, self.STATE_STREAMING, self.STATE_RECONNECTING)
    
    def add_observer(self, callback: Callable[[], None]) -> None:
        """Add an observer to be notified on state changes.
        
        Args:
            callback: Function to call when state changes (no arguments).
        """
        with self._lock:
            if callback not in self._observers:
                self._observers.append(callback)
    
    def remove_observer(self, callback: Callable[[], None]) -> None:
        """Remove an observer.
        
        Args:
            callback: Previously registered callback to remove.
        """
        with self._lock:
            if callback in self._observers:
                self._observers.remove(callback)
    
    def _notify_observers(self) -> None:
        """Notify all observers of a state change."""
        with self._lock:
            observers = list(self._observers)
        
        for callback in observers:
            try:
                callback()
            except Exception as e:
                log.debug(f"[ChromecastService] Observer callback error: {e}")
    
    def start_streaming(self, device_name: str) -> bool:
        """Start streaming to the specified Chromecast device.
        
        If already streaming, stops the current stream first.
        
        Args:
            device_name: Friendly name of the Chromecast device
            
        Returns:
            True if streaming started, False on immediate failure.
        """
        # Stop any existing stream
        if self._running:
            self.stop_streaming()
        
        self._device_name = device_name
        self._state = self.STATE_CONNECTING
        self._error_message = None
        self._stop_event.clear()
        self._running = True
        
        self._thread = threading.Thread(
            target=self._streaming_loop,
            name="chromecast-service",
            daemon=True
        )
        self._thread.start()
        
        log.info(f"[ChromecastService] Starting stream to: {device_name}")
        self._save_state()
        self._notify_observers()
        return True
    
    def stop_streaming(self) -> None:
        """Stop the current stream and disconnect from Chromecast."""
        if not self._running:
            return
        
        log.info("[ChromecastService] Stopping stream")
        self._running = False
        self._stop_event.set()
        
        # Stop media playback
        if self._chromecast:
            try:
                mc = self._chromecast.media_controller
                mc.stop()
            except Exception as e:
                log.debug(f"[ChromecastService] Error stopping media: {e}")
        
        # Wait for thread to finish
        if self._thread:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                log.warning("[ChromecastService] Thread did not stop within timeout")
            self._thread = None
        
        # Cleanup pychromecast objects
        self._cleanup_chromecast()
        
        self._state = self.STATE_IDLE
        self._device_name = None
        self._save_state()  # Clear persisted state
        self._notify_observers()
    
    def _cleanup_chromecast(self) -> None:
        """Clean up pychromecast browser and device connections."""
        if self._browser:
            try:
                self._browser.stop_discovery()
            except Exception:
                pass
            self._browser = None
        
        if self._chromecast:
            try:
                self._chromecast.disconnect()
            except Exception:
                pass
            self._chromecast = None
    
    def _streaming_loop(self) -> None:
        """Background thread that manages the Chromecast connection.
        
        Connects to the device, starts streaming, and reconnects if the
        connection is lost.
        """
        try:
            import pychromecast
            from DGTCentaurMods.board import network
        except ImportError as e:
            log.error(f"[ChromecastService] Missing dependency: {e}")
            self._state = self.STATE_ERROR
            self._error_message = "Missing pychromecast"
            self._notify_observers()
            return
        
        while self._running and not self._stop_event.is_set():
            try:
                # Discover Chromecasts
                log.info("[ChromecastService] Discovering Chromecasts...")
                chromecasts, self._browser = pychromecast.get_chromecasts()
                
                if self._stop_event.is_set():
                    break
                
                # Find the target device
                target_cc = None
                for cc in chromecasts:
                    if cc.device.friendly_name == self._device_name:
                        target_cc = cc
                        break
                
                if target_cc is None:
                    log.warning(f"[ChromecastService] Device '{self._device_name}' not found")
                    self._state = self.STATE_ERROR
                    self._error_message = "Device not found"
                    self._notify_observers()
                    # Wait before retrying
                    if self._stop_event.wait(timeout=10.0):
                        break
                    self._state = self.STATE_RECONNECTING
                    self._notify_observers()
                    continue
                
                self._chromecast = target_cc
                
                # Wait for connection
                log.info(f"[ChromecastService] Connecting to {self._device_name}...")
                self._chromecast.wait()
                
                if self._stop_event.is_set():
                    break
                
                # Get IP address and start streaming
                ip = network.check_network()
                if not ip:
                    log.error("[ChromecastService] No network connection")
                    self._state = self.STATE_ERROR
                    self._error_message = "No network"
                    self._notify_observers()
                    if self._stop_event.wait(timeout=10.0):
                        break
                    continue
                
                # Start media playback
                mc = self._chromecast.media_controller
                stream_url = f"http://{ip}/video?t={time.time()}"
                log.info(f"[ChromecastService] Starting stream: {stream_url}")
                
                mc.play_media(stream_url, 'image/jpeg', stream_type='LIVE')
                mc.block_until_active()
                mc.play()
                
                self._state = self.STATE_STREAMING
                self._notify_observers()
                log.info(f"[ChromecastService] Streaming to {self._device_name}")
                
                # Monitor the connection
                while self._running and not self._stop_event.is_set():
                    # Check if still playing (Default Media Receiver is the cast app)
                    if self._chromecast.status.display_name != 'Default Media Receiver':
                        log.info("[ChromecastService] Playback stopped externally")
                        break
                    
                    # Small sleep to avoid busy loop
                    if self._stop_event.wait(timeout=1.0):
                        break
                
                if not self._running or self._stop_event.is_set():
                    break
                
                # Playback stopped, prepare to reconnect
                log.info("[ChromecastService] Connection lost, will reconnect...")
                self._state = self.STATE_RECONNECTING
                self._notify_observers()
                
                # Cleanup before retry
                if self._browser:
                    try:
                        self._browser.stop_discovery()
                    except Exception:
                        pass
                    self._browser = None
                
            except Exception as e:
                log.error(f"[ChromecastService] Error in streaming loop: {e}")
                self._state = self.STATE_ERROR
                self._error_message = str(e)[:20]
                self._notify_observers()
                
                # Cleanup before retry
                self._cleanup_chromecast()
                
                # Wait before retrying
                if self._stop_event.wait(timeout=10.0):
                    break
                
                self._state = self.STATE_RECONNECTING
                self._notify_observers()
        
        # Final cleanup
        self._cleanup_chromecast()
        log.info("[ChromecastService] Streaming loop ended")


# Singleton instance
_chromecast_service: Optional[ChromecastService] = None
_service_lock = threading.Lock()


def get_chromecast_service() -> ChromecastService:
    """Get the global Chromecast service instance.
    
    Creates the service on first call (lazy initialization).
    
    Returns:
        The global ChromecastService singleton.
    """
    global _chromecast_service
    
    with _service_lock:
        if _chromecast_service is None:
            _chromecast_service = ChromecastService()
        return _chromecast_service
