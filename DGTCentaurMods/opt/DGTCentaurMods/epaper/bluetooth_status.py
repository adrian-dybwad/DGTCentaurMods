"""
Bluetooth status indicator widget.

Displays Bluetooth connection state in the status bar:
- Bluetooth icon when enabled and connected
- Bluetooth icon with X when disabled or disconnected
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
import threading
import subprocess
from typing import Optional

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# Bluetooth state constants
BT_DISABLED = 0
BT_DISCONNECTED = 1
BT_CONNECTED = 2


class BluetoothStatusWidget(Widget):
    """Bluetooth status indicator widget showing connection state.
    
    Displays a Bluetooth icon with different states:
    - Solid icon when connected
    - Outline icon when enabled but not connected
    - Icon with X overlay when disabled
    
    Args:
        x: X position
        y: Y position
        width: Widget width in pixels (default 12)
        height: Widget height in pixels (default 16)
        auto_update: If True, starts background thread for automatic updates
    """
    
    def __init__(self, x: int, y: int, width: int = 12, height: int = 16, auto_update: bool = True):
        super().__init__(x, y, width, height)
        self._width = width
        self._height = height
        self._last_state: Optional[int] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        if auto_update:
            self._start_update_loop()
    
    def _start_update_loop(self) -> None:
        """Start the background update loop."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._update_loop, 
            name="bluetooth-status-widget", 
            daemon=True
        )
        self._thread.start()
    
    def _stop_update_loop(self) -> None:
        """Stop the background update loop."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
    
    def stop(self) -> None:
        """Stop the widget and perform cleanup tasks."""
        self._stop_update_loop()
    
    def _update_loop(self) -> None:
        """Background loop that checks Bluetooth state every 10 seconds."""
        while self._running:
            try:
                state = self._get_bluetooth_status()
                
                # Update visibility based on Bluetooth enabled state
                should_be_visible = state != BT_DISABLED
                if self.visible != should_be_visible:
                    self.visible = should_be_visible
                    log.debug(f"Bluetooth widget visibility changed: {should_be_visible}")
                
                if state != self._last_state:
                    self._last_rendered = None
                    self._last_state = state
                    self.request_update(full=False)
                    log.debug(f"Bluetooth status changed: state={state}")
                
                # Sleep for 10 seconds, interruptible
                for _ in range(10):
                    if not self._running:
                        break
                    self._stop_event.wait(timeout=1.0)
                    self._stop_event.clear()
            except Exception as e:
                log.debug(f"Error in Bluetooth status update loop: {e}")
                for _ in range(10):
                    if not self._running:
                        break
                    self._stop_event.wait(timeout=1.0)
                    self._stop_event.clear()
    
    def _is_bluetooth_enabled(self) -> bool:
        """Check if Bluetooth is enabled (not blocked by rfkill)."""
        try:
            result = subprocess.run(
                ['rfkill', 'list', 'bluetooth'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return 'blocked: yes' not in result.stdout.lower()
        except Exception as e:
            log.debug(f"Error checking Bluetooth enabled state: {e}")
        return True  # Assume enabled if check fails
    
    def _is_bluetooth_connected(self) -> bool:
        """Check if any Bluetooth device is connected.
        
        Uses bluetoothctl to check for connected devices.
        """
        try:
            result = subprocess.run(
                ['bluetoothctl', 'devices', 'Connected'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                # Output contains "Device XX:XX:XX:XX:XX:XX Name" for each connected device
                return len(result.stdout.strip()) > 0
        except Exception as e:
            log.debug(f"Error checking Bluetooth connection: {e}")
        return False
    
    def _get_bluetooth_status(self) -> int:
        """Get Bluetooth connection state.
        
        Returns:
            BT_DISABLED, BT_DISCONNECTED, or BT_CONNECTED
        """
        if not self._is_bluetooth_enabled():
            return BT_DISABLED
        
        if self._is_bluetooth_connected():
            return BT_CONNECTED
        
        return BT_DISCONNECTED
    
    def _draw_bluetooth_icon(self, draw: ImageDraw.Draw, draw_x: int, draw_y: int, 
                             connected: bool = False) -> None:
        """Draw a Bluetooth icon.
        
        The icon is a stylized "B" shape with angular notches.
        Scales to fit within width x height.
        
        Args:
            draw: ImageDraw object
            draw_x: X offset on target image
            draw_y: Y offset on target image
            connected: If True, draw with thicker lines (connected state)
        """
        w = self._width
        h = self._height
        
        # Scale factors based on dimensions
        sx = w / 12.0   # horizontal scale (12 is base width)
        sy = h / 16.0   # vertical scale (16 is base height)
        
        # Center of icon
        cx = draw_x + w // 2
        cy = draw_y + h // 2
        
        # Bluetooth runic "B" shape
        top_y = draw_y + int(1 * sy)
        bottom_y = draw_y + h - int(1 * sy)
        
        line_width = 2 if connected else 1
        
        # Main vertical line
        draw.line([(cx, top_y), (cx, bottom_y)], fill=0, width=line_width)
        
        # Arrow points to the right
        arrow_right = cx + int(4 * sx)
        
        # Top arrow: center-top -> right corner -> center-middle
        draw.line([(cx, top_y), (arrow_right, cy - int(3 * sy))], fill=0, width=line_width)
        draw.line([(arrow_right, cy - int(3 * sy)), (cx, cy)], fill=0, width=line_width)
        
        # Bottom arrow: center-bottom -> right corner -> center-middle
        draw.line([(cx, bottom_y), (arrow_right, cy + int(3 * sy))], fill=0, width=line_width)
        draw.line([(arrow_right, cy + int(3 * sy)), (cx, cy)], fill=0, width=line_width)
    
    def _draw_disabled_cross(self, draw: ImageDraw.Draw, draw_x: int, draw_y: int) -> None:
        """Draw a cross overlay to indicate Bluetooth is disabled."""
        w = self._width
        h = self._height
        margin = 2
        line_width = 1
        
        draw.line([draw_x + margin, draw_y + margin, 
                   draw_x + w - margin, draw_y + h - margin], 
                  fill=0, width=line_width)
        draw.line([draw_x + w - margin, draw_y + margin, 
                   draw_x + margin, draw_y + h - margin], 
                  fill=0, width=line_width)
    
    def draw_on(self, img: Image.Image, draw_x: int, draw_y: int) -> None:
        """Draw Bluetooth status icon."""
        draw = ImageDraw.Draw(img)
        
        # Clear background
        draw.rectangle([draw_x, draw_y, draw_x + self.width - 1, draw_y + self.height - 1], 
                      fill=255)
        
        if self._last_state == BT_DISABLED:
            # Draw icon with cross overlay
            self._draw_bluetooth_icon(draw, draw_x, draw_y, connected=False)
            self._draw_disabled_cross(draw, draw_x, draw_y)
        elif self._last_state == BT_CONNECTED:
            # Draw solid icon
            self._draw_bluetooth_icon(draw, draw_x, draw_y, connected=True)
        else:
            # Disconnected - draw outline icon
            self._draw_bluetooth_icon(draw, draw_x, draw_y, connected=False)
