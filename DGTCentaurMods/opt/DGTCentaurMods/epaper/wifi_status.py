"""
WiFi status indicator widget.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
import threading
import time
import os
from typing import Optional

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

try:
    from DGTCentaurMods.board import network
except ImportError:
    network = None


class WiFiStatusWidget(Widget):
    """WiFi status indicator widget showing connection state."""
    
    def __init__(self, x: int, y: int):
        super().__init__(x, y, 16, 16)
        self._last_connected_state: Optional[bool] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # Path to dhcpcd hook notification file
        self._hook_notification_file = "/var/run/dgtcm-wifi-hook-notify"
        self._last_hook_mtime = 0.0
        self._stop_event = threading.Event()
        self._start_update_loop()
    
    def _start_update_loop(self) -> None:
        """Start the background update loop."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._update_loop, name="wifi-status-widget", daemon=True)
        self._thread.start()
    
    def _stop_update_loop(self) -> None:
        """Stop the background update loop."""
        self._running = False
        self._stop_event.set()  # Signal the event to wake up any sleeping thread
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
    
    def stop(self) -> None:
        """Stop the widget and perform cleanup tasks."""
        self._stop_update_loop()
    
    def _update_loop(self) -> None:
        """Background loop that checks WiFi state every 10 seconds and on dhcpcd hook notifications."""
        while self._running:
            try:
                # Check for dhcpcd hook notification
                hook_notified = False
                if os.path.exists(self._hook_notification_file):
                    try:
                        current_mtime = os.path.getmtime(self._hook_notification_file)
                        if current_mtime > self._last_hook_mtime:
                            self._last_hook_mtime = current_mtime
                            hook_notified = True
                            log.debug("WiFi status widget: dhcpcd hook notification detected")
                    except Exception as e:
                        log.debug(f"Error checking hook notification file: {e}")
                
                # Check WiFi connection state
                is_connected = self._is_connected()
                
                # Update if state changed or hook notified
                if is_connected != self._last_connected_state or hook_notified:
                    if is_connected != self._last_connected_state:
                        self._last_rendered = None
                        self.request_update(full=False)
                        self._last_connected_state = is_connected
                        log.debug(f"WiFi status changed: connected={is_connected}")
                    else:
                        log.debug(f"WiFi status did not change: connected={is_connected}")
                
                # Sleep for 10 seconds, but check _running every second
                # This allows the thread to stop quickly when requested
                for _ in range(10):
                    if not self._running:
                        break
                    self._stop_event.wait(timeout=1.0)
                    self._stop_event.clear()  # Clear the event for next iteration
            except Exception as e:
                log.error(f"Error in WiFi status update loop: {e}")
                # On error, also use interruptible sleep
                for _ in range(10):
                    if not self._running:
                        break
                    self._stop_event.wait(timeout=1.0)
                    self._stop_event.clear()
    
    def _is_connected(self) -> bool:
        """Check if WiFi is connected."""
        try:
            if network is None:
                return False
            result = network.check_network()
            return result is not False and result is not None
        except Exception as e:
            log.debug(f"Error checking WiFi status: {e}")
            return False
    
    def render(self) -> Image.Image:
        """Render WiFi status icon."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        if self._last_connected_state:
            # Draw connected WiFi icon (3 curved lines)
            # Top arc (signal strength 3/3)
            draw.arc([2, 2, 14, 14], start=45, end=135, fill=0, width=1)
            # Middle arc (signal strength 2/3)
            draw.arc([4, 4, 12, 12], start=45, end=135, fill=0, width=1)
            # Bottom arc (signal strength 1/3)
            draw.arc([6, 6, 10, 10], start=45, end=135, fill=0, width=1)
            # Dot in center
            draw.ellipse([7, 7, 9, 9], fill=0)
        else:
            # Draw disconnected WiFi icon (X with curved lines)
            # Top arc (faded)
            draw.arc([2, 2, 14, 14], start=45, end=135, fill=0, width=1)
            # Middle arc (faded)
            draw.arc([4, 4, 12, 12], start=45, end=135, fill=0, width=1)
            # X mark
            draw.line([2, 2, 14, 14], fill=0, width=1)
            draw.line([14, 2, 2, 14], fill=0, width=1)
        
        return img

