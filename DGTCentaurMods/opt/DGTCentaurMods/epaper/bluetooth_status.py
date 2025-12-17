"""
Bluetooth status module.

Provides:
- Functions to query Bluetooth adapter status and format information for menus
- Widget for displaying Bluetooth connection state in the status bar
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
import threading
import subprocess
from typing import Optional, List

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# Bluetooth state constants (for widget)
BT_DISABLED = 0
BT_DISCONNECTED = 1
BT_CONNECTED = 2

# Advertised service names for different protocols
ADVERTISED_NAMES = {
    'pegasus': 'DGT PEGASUS',
    'millennium': 'MILLENNIUM CHESS',
    'chessnut': 'Chessnut Air',
}


def get_bluetooth_status(device_name: Optional[str] = None,
                         ble_manager=None,
                         rfcomm_connected: bool = False) -> dict:
    """Get current Bluetooth adapter status and information.
    
    Args:
        device_name: The primary advertised device name
        ble_manager: Optional BleManager instance to check BLE connection status
        rfcomm_connected: Whether an RFCOMM client is connected
    
    Returns:
        Dictionary with keys:
        - enabled: bool, whether Bluetooth is enabled (not blocked by rfkill)
        - powered: bool, whether adapter is powered on
        - device_name: str, the primary advertised device name
        - address: str, the Bluetooth MAC address
        - ble_connected: bool, whether a BLE client is connected
        - ble_client_type: str or None, type of connected BLE client
        - rfcomm_connected: bool, whether an RFCOMM client is connected
        - advertised_names: list of str, all names being advertised
    """
    status = {
        'enabled': False,
        'powered': False,
        'device_name': device_name,
        'address': '',
        'ble_connected': False,
        'ble_client_type': None,
        'rfcomm_connected': rfcomm_connected,
        'advertised_names': list(ADVERTISED_NAMES.values()),
    }
    
    # Check rfkill status
    try:
        result = subprocess.run(['rfkill', 'list', 'bluetooth'],
                               capture_output=True, text=True, timeout=5)
        # If "Soft blocked: no" is in output, Bluetooth is enabled
        status['enabled'] = 'Soft blocked: no' in result.stdout
    except Exception as e:
        log.warning(f"[Bluetooth] Failed to check rfkill status: {e}")
    
    # Get adapter address via hciconfig
    try:
        result = subprocess.run(['hciconfig', 'hci0'],
                               capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Parse output for BD Address
            for line in result.stdout.split('\n'):
                if 'BD Address:' in line:
                    parts = line.split('BD Address:')
                    if len(parts) > 1:
                        addr = parts[1].strip().split()[0]
                        status['address'] = addr
                if 'UP RUNNING' in line:
                    status['powered'] = True
    except Exception as e:
        log.warning(f"[Bluetooth] Failed to get adapter info: {e}")
    
    # Check BLE connection status
    if ble_manager is not None:
        status['ble_connected'] = ble_manager.connected
        status['ble_client_type'] = getattr(ble_manager, 'client_type', None)
    
    return status


def format_status_label(status: dict) -> str:
    """Format Bluetooth status into a multi-line label for display.
    
    Shows device name, MAC address, connection status, and connected client type.
    
    Args:
        status: Dictionary from get_bluetooth_status()
        
    Returns:
        Multi-line string for display
    """
    lines = []
    
    # Device name
    lines.append(status['device_name'])
    
    # MAC address
    if status['address']:
        lines.append(status['address'])
    
    # Connection status
    if status['ble_connected']:
        client_type = status.get('ble_client_type', 'BLE')
        if client_type:
            lines.append(f"BLE: {client_type}")
        else:
            lines.append("BLE: Connected")
    elif status['rfcomm_connected']:
        lines.append("RFCOMM: Connected")
    elif status['enabled'] and status['powered']:
        lines.append("Ready")
    elif status['enabled']:
        lines.append("Enabled")
    else:
        lines.append("Disabled")
    
    return '\n'.join(lines)


def get_advertised_names_label() -> str:
    """Get a formatted label showing all advertised names.
    
    Returns:
        Multi-line string with all advertised names
    """
    return '\n'.join(ADVERTISED_NAMES.values())


def enable_bluetooth() -> bool:
    """Enable Bluetooth via rfkill.
    
    Returns:
        True if command succeeded, False otherwise
    """
    try:
        subprocess.run(['sudo', 'rfkill', 'unblock', 'bluetooth'], timeout=5)
        log.info("[Bluetooth] Enabled via rfkill")
        return True
    except Exception as e:
        log.error(f"[Bluetooth] Failed to enable: {e}")
        return False


def disable_bluetooth() -> bool:
    """Disable Bluetooth via rfkill.
    
    Returns:
        True if command succeeded, False otherwise
    """
    try:
        subprocess.run(['sudo', 'rfkill', 'block', 'bluetooth'], timeout=5)
        log.info("[Bluetooth] Disabled via rfkill")
        return True
    except Exception as e:
        log.error(f"[Bluetooth] Failed to disable: {e}")
        return False


class BluetoothStatusWidget(Widget):
    """Bluetooth status indicator widget showing connection state.
    
    Displays a Bluetooth icon with different states:
    - Solid icon when connected
    - Outline icon when enabled but not connected
    - Icon with X overlay when disabled
    
    Args:
        x: X position
        y: Y position
        width: Widget width in pixels
        height: Widget height in pixels
        update_callback: Callback to trigger display updates. Must not be None.
        auto_update: If True, starts background thread for automatic updates
    """
    
    def __init__(self, x: int, y: int, width: int, height: int, update_callback, auto_update: bool = True):
        super().__init__(x, y, width, height, update_callback)
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
        Scales to fit within width x height, with 1px margin on all sides.
        
        Args:
            draw: ImageDraw object
            draw_x: X offset on target image
            draw_y: Y offset on target image
            connected: If True, draw with thicker lines (connected state)
        """
        # 1px margin around the icon
        margin = 1
        icon_x = draw_x + margin
        icon_y = draw_y + margin
        icon_w = self._width - 2 * margin
        icon_h = self._height - 2 * margin
        
        # Scale factors based on icon dimensions (10x14 base for 12x16 widget)
        sx = icon_w / 10.0
        sy = icon_h / 14.0
        
        # Vertical center of icon area
        cy = icon_y + icon_h // 2
        
        # The vertical line position: shift left to balance visual weight
        # since arrows only extend to the right. Place at ~1/3 of icon width.
        cx = icon_x + icon_w // 3
        
        # Bluetooth runic "B" shape
        top_y = icon_y
        bottom_y = icon_y + icon_h - 1
        
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
        """Draw a cross overlay to indicate Bluetooth is disabled.
        
        Uses 1px margin to match the icon margin.
        """
        margin = 1
        x1 = draw_x + margin
        y1 = draw_y + margin
        x2 = draw_x + self._width - margin - 1
        y2 = draw_y + self._height - margin - 1
        
        draw.line([(x1, y1), (x2, y2)], fill=0, width=1)
        draw.line([(x2, y1), (x1, y2)], fill=0, width=1)
    
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
