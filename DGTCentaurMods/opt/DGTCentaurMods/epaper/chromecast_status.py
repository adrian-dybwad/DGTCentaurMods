"""
Chromecast status widget with streaming functionality.

This widget:
1. Displays a cast icon in the status bar when streaming is active
2. Manages the Chromecast connection in a background thread
3. Monitors the connection and reconnects if needed

The widget is hidden when not streaming.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
import threading
import time
from typing import Optional

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class ChromecastStatusWidget(Widget):
    """Chromecast status widget that manages streaming and displays status icon.
    
    When streaming is active, displays a small cast icon in the status bar.
    When not streaming, the widget is hidden (draws nothing).
    
    The widget manages the Chromecast connection internally, replacing the
    separate cchandler.py process.
    
    Args:
        x: X position in status bar
        y: Y position in status bar
        size: Icon size in pixels (default 14 for status bar)
    """
    
    # Streaming states
    STATE_IDLE = 0
    STATE_CONNECTING = 1
    STATE_STREAMING = 2
    STATE_RECONNECTING = 3
    STATE_ERROR = 4
    
    def __init__(self, x: int, y: int, size: int = 14):
        super().__init__(x, y, size, size)
        self._size = size
        
        # Start hidden - only visible when streaming
        self.visible = False
        
        # Streaming state
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
    
    @property
    def state(self) -> int:
        """Return current streaming state."""
        return self._state
    
    @property
    def device_name(self) -> Optional[str]:
        """Return the name of the connected Chromecast device."""
        return self._device_name
    
    def start_streaming(self, device_name: str) -> bool:
        """Start streaming to the specified Chromecast device.
        
        If already streaming, stops the current stream first.
        
        Args:
            device_name: Friendly name of the Chromecast device
            
        Returns:
            True if streaming started successfully, False otherwise
        """
        # Stop any existing stream
        if self._running:
            self.stop_streaming()
        
        self._device_name = device_name
        self._state = self.STATE_CONNECTING
        self._error_message = None
        self._stop_event.clear()
        self._running = True
        
        # Show the widget now that we're streaming
        self.visible = True
        
        self._thread = threading.Thread(
            target=self._streaming_loop,
            name="chromecast-status",
            daemon=True
        )
        self._thread.start()
        
        log.info(f"[ChromecastStatus] Starting stream to: {device_name}")
        self._last_rendered = None
        self.request_update(full=False)
        return True
    
    def stop_streaming(self) -> None:
        """Stop the current stream and disconnect from Chromecast."""
        if not self._running:
            return
        
        log.info("[ChromecastStatus] Stopping stream")
        self._running = False
        self._stop_event.set()
        
        # Hide the widget
        self.visible = False
        
        # Stop media playback
        if self._chromecast:
            try:
                mc = self._chromecast.media_controller
                mc.stop()
            except Exception as e:
                log.debug(f"[ChromecastStatus] Error stopping media: {e}")
        
        # Wait for thread to finish
        if self._thread:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                log.warning("[ChromecastStatus] Thread did not stop within timeout")
            self._thread = None
        
        # Cleanup pychromecast objects
        self._cleanup_chromecast()
        
        self._state = self.STATE_IDLE
        self._device_name = None
        self._last_rendered = None
        self.request_update(full=False)
    
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
            log.error(f"[ChromecastStatus] Missing dependency: {e}")
            self._state = self.STATE_ERROR
            self._error_message = "Missing pychromecast"
            return
        
        while self._running and not self._stop_event.is_set():
            try:
                # Discover Chromecasts
                log.info(f"[ChromecastStatus] Discovering Chromecasts...")
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
                    log.warning(f"[ChromecastStatus] Device '{self._device_name}' not found")
                    self._state = self.STATE_ERROR
                    self._error_message = "Device not found"
                    self._last_rendered = None
                    self.request_update(full=False)
                    # Wait before retrying
                    if self._stop_event.wait(timeout=10.0):
                        break
                    self._state = self.STATE_RECONNECTING
                    continue
                
                self._chromecast = target_cc
                
                # Wait for connection
                log.info(f"[ChromecastStatus] Connecting to {self._device_name}...")
                self._chromecast.wait()
                
                if self._stop_event.is_set():
                    break
                
                # Get IP address and start streaming
                ip = network.check_network()
                if not ip:
                    log.error("[ChromecastStatus] No network connection")
                    self._state = self.STATE_ERROR
                    self._error_message = "No network"
                    if self._stop_event.wait(timeout=10.0):
                        break
                    continue
                
                # Start media playback
                mc = self._chromecast.media_controller
                stream_url = f"http://{ip}/video?t={time.time()}"
                log.info(f"[ChromecastStatus] Starting stream: {stream_url}")
                
                mc.play_media(stream_url, 'image/jpeg', stream_type='LIVE')
                mc.block_until_active()
                mc.play()
                
                self._state = self.STATE_STREAMING
                self._last_rendered = None
                self.request_update(full=False)
                log.info(f"[ChromecastStatus] Streaming to {self._device_name}")
                
                # Monitor the connection
                while self._running and not self._stop_event.is_set():
                    # Check if still playing (Default Media Receiver is the cast app)
                    if self._chromecast.status.display_name != 'Default Media Receiver':
                        log.info("[ChromecastStatus] Playback stopped externally")
                        break
                    
                    # Small sleep to avoid busy loop
                    if self._stop_event.wait(timeout=1.0):
                        break
                
                if not self._running or self._stop_event.is_set():
                    break
                
                # Playback stopped, prepare to reconnect
                log.info("[ChromecastStatus] Connection lost, will reconnect...")
                self._state = self.STATE_RECONNECTING
                self._last_rendered = None
                self.request_update(full=False)
                
                # Cleanup before retry
                if self._browser:
                    try:
                        self._browser.stop_discovery()
                    except Exception:
                        pass
                    self._browser = None
                
            except Exception as e:
                log.error(f"[ChromecastStatus] Error in streaming loop: {e}")
                self._state = self.STATE_ERROR
                self._error_message = str(e)[:20]
                self._last_rendered = None
                self.request_update(full=False)
                
                # Cleanup before retry
                self._cleanup_chromecast()
                
                # Wait before retrying
                if self._stop_event.wait(timeout=10.0):
                    break
                
                self._state = self.STATE_RECONNECTING
        
        # Final cleanup
        self._cleanup_chromecast()
        log.info("[ChromecastStatus] Streaming loop ended")
    
    def stop(self) -> None:
        """Stop the widget and clean up resources."""
        self.stop_streaming()
    
    def _draw_cast_icon(self, draw: ImageDraw.Draw, draw_x: int, draw_y: int, 
                        filled: bool = True) -> None:
        """Draw a Chromecast-style cast icon.
        
        Args:
            draw: ImageDraw object
            draw_x: X offset on target image
            draw_y: Y offset on target image
            filled: If True, draw filled icon (streaming). If False, outline only.
        """
        s = self._size / 14.0  # Scale factor (14 is base size)
        
        # TV/monitor outline
        tv_left = draw_x + int(1 * s)
        tv_top = draw_y + int(2 * s)
        tv_right = draw_x + int(13 * s)
        tv_bottom = draw_y + int(10 * s)
        
        # Draw TV outline
        draw.rectangle([tv_left, tv_top, tv_right, tv_bottom], fill=255, outline=0, width=1)
        
        # Draw wireless signal arcs (bottom-left corner)
        arc_x = tv_left + int(2 * s)
        arc_y = tv_bottom - int(2 * s)
        
        if filled:
            # When streaming: filled arcs
            for i, radius in enumerate([int(2 * s), int(4 * s)]):
                if radius > 0:
                    draw.arc([arc_x - radius, arc_y - radius, 
                             arc_x + radius, arc_y + radius],
                            start=180, end=270, fill=0, width=max(1, int(1.5 * s)))
            
            # Small dot at origin
            dot_r = max(1, int(1 * s))
            draw.ellipse([arc_x - dot_r, arc_y - dot_r, arc_x + dot_r, arc_y + dot_r], fill=0)
        else:
            # When connecting/error: just outline arcs (thinner)
            for radius in [int(2 * s), int(4 * s)]:
                if radius > 0:
                    draw.arc([arc_x - radius, arc_y - radius, 
                             arc_x + radius, arc_y + radius],
                            start=180, end=270, fill=0, width=1)
    
    def draw_on(self, img: Image.Image, draw_x: int, draw_y: int) -> None:
        """Draw the Chromecast status icon.
        
        Visibility is controlled by the parent via the `visible` property.
        This method draws the icon based on the current streaming state.
        """
        draw = ImageDraw.Draw(img)
        
        # Clear background
        draw.rectangle([draw_x, draw_y, draw_x + self.width - 1, draw_y + self.height - 1], 
                      fill=255)
        
        # Draw icon based on state
        if self._state == self.STATE_STREAMING:
            # Solid icon when streaming
            self._draw_cast_icon(draw, draw_x, draw_y, filled=True)
        elif self._state in (self.STATE_CONNECTING, self.STATE_RECONNECTING):
            # Outline icon when connecting
            self._draw_cast_icon(draw, draw_x, draw_y, filled=False)
        elif self._state == self.STATE_ERROR:
            # Icon with X overlay when error
            self._draw_cast_icon(draw, draw_x, draw_y, filled=False)
            # Draw small X
            s = self._size / 14.0
            x1 = draw_x + int(8 * s)
            y1 = draw_y + int(2 * s)
            x2 = draw_x + int(13 * s)
            y2 = draw_y + int(7 * s)
            draw.line([x1, y1, x2, y2], fill=0, width=1)
            draw.line([x1, y2, x2, y1], fill=0, width=1)


# Singleton instance for global access
_chromecast_widget: Optional[ChromecastStatusWidget] = None


def get_chromecast_widget() -> Optional[ChromecastStatusWidget]:
    """Get the global Chromecast status widget instance.
    
    Returns:
        The global ChromecastStatusWidget instance, or None if not created.
    """
    return _chromecast_widget


def set_chromecast_widget(widget: ChromecastStatusWidget) -> None:
    """Set the global Chromecast status widget instance.
    
    Args:
        widget: The ChromecastStatusWidget instance to use globally.
    """
    global _chromecast_widget
    _chromecast_widget = widget
