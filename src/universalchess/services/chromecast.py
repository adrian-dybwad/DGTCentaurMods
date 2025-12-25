"""
Chromecast streaming service.

Manages the Chromecast connection and streaming lifecycle.
The state is held in state/chromecast.py - this service owns
the threading and connection logic.

Also provides the e-paper JPEG export function used for web/Chromecast streaming.
"""

import os
import threading
import time
from typing import Optional

try:
    from universalchess.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

# Path for e-paper static JPEG (used by web and Chromecast streaming)
from universalchess.paths import EPAPER_STATIC_JPG
from universalchess.state import get_chromecast as get_chromecast_state


def write_epaper_jpg(image) -> str:
    """Write the provided Pillow Image to web/static/epaper.jpg for streaming.
    
    The image will be converted to a JPEG-compatible mode if needed.
    The image is rotated 180 degrees before saving to correct orientation
    for Chromecast streaming.
    
    Args:
        image: PIL Image to save
        
    Returns:
        Path where image was saved
        
    Raises:
        TypeError: If image is not a PIL Image
    """
    from PIL import Image
    
    if not isinstance(image, Image.Image):
        raise TypeError("write_epaper_jpg expects a PIL Image")
    
    # Ensure parent directory exists
    parent = os.path.dirname(EPAPER_STATIC_JPG)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except PermissionError:
            log.error(f"Permission denied creating directory: {parent}")
            raise
    
    img = image
    if img.mode not in ("L", "RGB"):
        img = img.convert("L")
    
    # Rotate 180 degrees to correct orientation for streaming
    img = img.rotate(180)
    img.save(EPAPER_STATIC_JPG, format="JPEG")
    return EPAPER_STATIC_JPG


class ChromecastService:
    """Service managing Chromecast streaming.
    
    The service:
    - Owns the streaming thread
    - Manages device discovery and connection
    - Updates the state object which notifies observers
    
    Widgets should import from state/, not this service.
    """
    
    def __init__(self):
        """Initialize the Chromecast service."""
        self._state = get_chromecast_state()
        
        # Thread management
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        
        # pychromecast objects (lazy loaded)
        self._chromecast = None
        self._browser = None
        self._lock = threading.Lock()
    
    # -------------------------------------------------------------------------
    # Properties (delegate to state for reads)
    # -------------------------------------------------------------------------
    
    @property
    def state(self) -> int:
        """Current streaming state."""
        return self._state.state
    
    @property
    def device_name(self) -> Optional[str]:
        """Name of the connected Chromecast device."""
        return self._state.device_name
    
    @property
    def error_message(self) -> Optional[str]:
        """Error message if in error state."""
        return self._state.error_message
    
    @property
    def is_active(self) -> bool:
        """True if streaming or attempting to stream."""
        return self._state.is_active
    
    # -------------------------------------------------------------------------
    # Observer management (delegate to state)
    # -------------------------------------------------------------------------
    
    def add_observer(self, callback) -> None:
        """Add an observer to be notified on state changes."""
        self._state.add_observer(callback)
    
    def remove_observer(self, callback) -> None:
        """Remove an observer."""
        self._state.remove_observer(callback)
    
    # -------------------------------------------------------------------------
    # Streaming control
    # -------------------------------------------------------------------------
    
    def start_streaming(self, device_name: str) -> bool:
        """Start streaming to the specified Chromecast device.
        
        Args:
            device_name: Friendly name of the Chromecast device
            
        Returns:
            True if streaming started, False on immediate failure.
        """
        # Stop any existing stream
        if self._running:
            self.stop_streaming()
        
        self._state.set_connecting(device_name)
        self._stop_event.clear()
        self._running = True
        
        self._thread = threading.Thread(
            target=self._streaming_loop,
            name="chromecast-service",
            daemon=True
        )
        self._thread.start()
        
        log.info(f"[ChromecastService] Starting stream to: {device_name}")
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
        
        self._state.set_idle()
    
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
        """Background thread that manages the Chromecast connection."""
        try:
            import pychromecast
            from universalchess.board import network
        except ImportError as e:
            log.error(f"[ChromecastService] Missing dependency: {e}")
            self._state.set_error("Missing pychromecast")
            return
        
        device_name = self._state.device_name
        
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
                    if cc.device.friendly_name == device_name:
                        target_cc = cc
                        break
                
                if target_cc is None:
                    log.warning(f"[ChromecastService] Device '{device_name}' not found")
                    self._state.set_error("Device not found")
                    # Wait before retrying
                    if self._stop_event.wait(timeout=10.0):
                        break
                    self._state.set_reconnecting()
                    continue
                
                self._chromecast = target_cc
                
                # Wait for connection
                log.info(f"[ChromecastService] Connecting to {device_name}...")
                self._chromecast.wait()
                
                if self._stop_event.is_set():
                    break
                
                # Get IP address and start streaming
                ip = network.check_network()
                if not ip:
                    log.error("[ChromecastService] No network connection")
                    self._state.set_error("No network")
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
                
                self._state.set_streaming(device_name)
                log.info(f"[ChromecastService] Streaming to {device_name}")
                
                # Monitor the connection
                while self._running and not self._stop_event.is_set():
                    # Check if still playing
                    if self._chromecast.status.display_name != 'Default Media Receiver':
                        log.info("[ChromecastService] Playback stopped externally")
                        break
                    
                    if self._stop_event.wait(timeout=1.0):
                        break
                
                if not self._running or self._stop_event.is_set():
                    break
                
                # Playback stopped, prepare to reconnect
                log.info("[ChromecastService] Connection lost, will reconnect...")
                self._state.set_reconnecting()
                
                # Cleanup before retry
                if self._browser:
                    try:
                        self._browser.stop_discovery()
                    except Exception:
                        pass
                    self._browser = None
                
            except Exception as e:
                log.error(f"[ChromecastService] Error in streaming loop: {e}")
                self._state.set_error(str(e)[:20])
                
                # Cleanup before retry
                self._cleanup_chromecast()
                
                # Wait before retrying
                if self._stop_event.wait(timeout=10.0):
                    break
                
                self._state.set_reconnecting()
        
        # Final cleanup
        self._cleanup_chromecast()
        log.info("[ChromecastService] Streaming loop ended")


# -----------------------------------------------------------------------------
# Singleton instance
# -----------------------------------------------------------------------------

_instance: Optional[ChromecastService] = None
_lock = threading.Lock()


def get_chromecast_service() -> ChromecastService:
    """Get the global Chromecast service instance.
    
    Returns:
        The global ChromecastService singleton.
    """
    global _instance
    
    with _lock:
        if _instance is None:
            _instance = ChromecastService()
        return _instance
