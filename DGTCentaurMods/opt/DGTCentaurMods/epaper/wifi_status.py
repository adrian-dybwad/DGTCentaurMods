"""
WiFi status indicator widget.

Displays WiFi signal strength in the status bar using the same icon style
as the WiFi menu icons. Shows:
- Signal strength (1-3 bars) when connected
- Cross overlay when WiFi is disabled
- No signal bars when not connected but enabled
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
import threading
import subprocess
import re
import os
from typing import Optional, Tuple

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

try:
    from DGTCentaurMods.board import network
except ImportError:
    network = None


# WiFi state constants
WIFI_DISABLED = 0
WIFI_DISCONNECTED = 1
WIFI_CONNECTED = 2


class WiFiStatusWidget(Widget):
    """WiFi status indicator widget showing connection state and signal strength.
    
    Uses the same icon style as the WiFi menu icons:
    - Concentric arcs showing signal strength (1-3 based on signal %)
    - Cross overlay when WiFi is disabled
    """
    
    def __init__(self, x: int, y: int):
        super().__init__(x, y, 16, 16)
        self._last_state: Optional[int] = None  # WIFI_DISABLED, WIFI_DISCONNECTED, WIFI_CONNECTED
        self._last_signal_strength: int = 0  # 0-3 (0 = no signal, 1-3 = weak/medium/strong)
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
            log.debug(f"WiFiStatusWidget._start_update_loop(): Widget id={id(self)} already running, skipping")
            return
        self._running = True
        self._thread = threading.Thread(target=self._update_loop, name="wifi-status-widget", daemon=True)
        self._thread.start()
        log.debug(f"WiFiStatusWidget._start_update_loop(): Widget id={id(self)} thread started, thread_id={self._thread.ident}")
    
    def _stop_update_loop(self) -> None:
        """Stop the background update loop."""
        log.debug(f"WiFiStatusWidget._stop_update_loop(): Widget id={id(self)} stopping, thread_id={self._thread.ident if self._thread else None}")
        self._running = False
        self._stop_event.set()  # Signal the event to wake up any sleeping thread
        if self._thread:
            thread_id = self._thread.ident
            self._thread.join(timeout=1.0)
            if self._thread.is_alive():
                log.warning(f"WiFiStatusWidget._stop_update_loop(): Widget id={id(self)} thread {thread_id} did not stop within timeout")
            else:
                log.debug(f"WiFiStatusWidget._stop_update_loop(): Widget id={id(self)} thread {thread_id} stopped successfully")
            self._thread = None
    
    def stop(self) -> None:
        """Stop the widget and perform cleanup tasks."""
        self._stop_update_loop()
    
    def _update_loop(self) -> None:
        """Background loop that checks WiFi state every 10 seconds and on dhcpcd hook notifications."""
        thread_id = threading.get_ident()
        log.debug(f"WiFiStatusWidget._update_loop(): Widget id={id(self)} thread {thread_id} started")
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
                
                # Get WiFi state and signal strength
                state, signal_strength = self._get_wifi_status()
                
                # Update if state or signal changed or hook notified
                if state != self._last_state or signal_strength != self._last_signal_strength or hook_notified:
                    self._last_rendered = None
                    self._last_state = state
                    self._last_signal_strength = signal_strength
                    self.request_update(full=False)
                    log.debug(f"WiFi status changed: state={state}, signal={signal_strength}")
                
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
        log.debug(f"WiFiStatusWidget._update_loop(): Widget id={id(self)} thread {thread_id} exiting")
    
    def _is_wifi_enabled(self) -> bool:
        """Check if WiFi is enabled (not blocked by rfkill)."""
        try:
            result = subprocess.run(['rfkill', 'list', 'wifi'],
                                   capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                # Check for "Soft blocked: yes" or "Hard blocked: yes"
                return 'blocked: yes' not in result.stdout.lower()
        except Exception as e:
            log.debug(f"Error checking WiFi enabled state: {e}")
        return True  # Assume enabled if check fails
    
    def _get_signal_strength(self) -> int:
        """Get current WiFi signal strength as percentage (0-100).
        
        Uses iwconfig to get the Link Quality.
        
        Returns:
            Signal strength percentage, or 0 if not available
        """
        try:
            result = subprocess.run(['iwconfig', 'wlan0'],
                                   capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                # Parse "Link Quality=XX/70" from output
                match = re.search(r'Link Quality[=:](\d+)/(\d+)', result.stdout)
                if match:
                    quality = int(match.group(1))
                    max_quality = int(match.group(2))
                    if max_quality > 0:
                        return int((quality / max_quality) * 100)
                
                # Alternative: parse "Signal level=-XX dBm"
                match = re.search(r'Signal level[=:](-?\d+)\s*dBm', result.stdout)
                if match:
                    dbm = int(match.group(1))
                    # Convert dBm to percentage (rough approximation)
                    # -30 dBm = 100%, -90 dBm = 0%
                    return max(0, min(100, (dbm + 90) * 100 // 60))
        except Exception as e:
            log.debug(f"Error getting signal strength: {e}")
        return 0
    
    def _get_wifi_status(self) -> Tuple[int, int]:
        """Get WiFi connection state and signal strength.
        
        Returns:
            Tuple of (state, signal_strength) where:
            - state: WIFI_DISABLED, WIFI_DISCONNECTED, or WIFI_CONNECTED
            - signal_strength: 0-3 (0 = no signal, 1-3 = weak/medium/strong)
        """
        # Check if WiFi is enabled
        if not self._is_wifi_enabled():
            return WIFI_DISABLED, 0
        
        # Check if connected
        try:
            if network is None:
                return WIFI_DISCONNECTED, 0
            result = network.check_network()
            is_connected = result is not False and result is not None
        except Exception:
            is_connected = False
        
        if not is_connected:
            return WIFI_DISCONNECTED, 0
        
        # Get signal strength
        signal_pct = self._get_signal_strength()
        
        # Convert percentage to 1-3 strength
        if signal_pct >= 70:
            strength = 3
        elif signal_pct >= 40:
            strength = 2
        else:
            strength = 1
        
        return WIFI_CONNECTED, strength
    
    def _draw_wifi_signal_icon(self, draw: ImageDraw.Draw, strength: int = 3):
        """Draw a WiFi signal icon with variable strength.
        
        Uses the same style as icon_button.py but scaled for 16x16 status bar.
        
        Args:
            draw: ImageDraw object
            strength: Signal strength 1-3 (1=weak, 2=medium, 3=strong)
        """
        # Center point and base position (bottom center of icon)
        cx = 8
        base_y = 13
        
        # Arc radii for 16x16 icon
        radii = [3, 6, 9]
        
        for i, radius in enumerate(radii):
            # Determine line width based on active/inactive
            if i < strength:
                # Active arc - thicker line
                width = 2
            else:
                # Inactive arc - thin line
                width = 1
            
            draw.arc([cx - radius, base_y - radius, cx + radius, base_y + radius],
                    start=225, end=315, fill=0, width=width)
        
        # Small dot at the bottom center (always drawn)
        draw.ellipse([cx - 1, base_y - 1, cx + 1, base_y + 1], fill=0)
    
    def _draw_disabled_cross(self, draw: ImageDraw.Draw):
        """Draw a cross overlay to indicate WiFi is disabled."""
        # Draw diagonal cross over the icon
        draw.line([2, 2, 14, 14], fill=0, width=2)
        draw.line([14, 2, 2, 14], fill=0, width=2)
    
    def render(self) -> Image.Image:
        """Render WiFi status icon with signal strength or disabled indicator."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        if self._last_state == WIFI_DISABLED:
            # Draw WiFi icon with cross overlay
            self._draw_wifi_signal_icon(draw, strength=0)
            self._draw_disabled_cross(draw)
        elif self._last_state == WIFI_CONNECTED:
            # Draw WiFi icon with signal strength
            self._draw_wifi_signal_icon(draw, strength=self._last_signal_strength)
        else:
            # Disconnected but enabled - show empty arcs
            self._draw_wifi_signal_icon(draw, strength=0)
        
        return img

