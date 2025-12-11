"""
Battery level indicator widget.

The widget manages its own state by polling the board controller every 5 seconds.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
import os
import sys
import threading
import time

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

try:
    from DGTCentaurMods.asset_manager import AssetManager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from asset_manager import AssetManager

# Polling interval for battery status (seconds)
BATTERY_POLL_INTERVAL = 5


class BatteryWidget(Widget):
    """Battery level indicator using bitmap icons.
    
    Manages its own state by polling the board controller every 5 seconds.
    Automatically starts polling when added to display and stops when removed.
    """
    
    def __init__(self, x: int, y: int, level: int = None, charger_connected: bool = False):
        super().__init__(x, y, 16, 16)
        self.level = level
        self.charger_connected = charger_connected
        self._use_bitmap_icons = True
        self._poll_thread = None
        self._stop_event = threading.Event()
    
    def start(self) -> None:
        """Start the battery polling thread."""
        if self._poll_thread is None or not self._poll_thread.is_alive():
            self._stop_event.clear()
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
            log.debug("BatteryWidget polling thread started")
    
    def stop(self) -> None:
        """Stop the battery polling thread."""
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
            self._poll_thread = None
            log.debug("BatteryWidget polling thread stopped")
    
    def _poll_loop(self) -> None:
        """Background thread that polls battery status every 5 seconds."""
        while not self._stop_event.is_set():
            try:
                self._fetch_battery_status()
            except Exception as e:
                log.debug(f"Error in battery poll loop: {e}")
            
            # Wait for next poll interval, but check stop event frequently
            for _ in range(BATTERY_POLL_INTERVAL * 10):
                if self._stop_event.is_set():
                    return
                time.sleep(0.1)
    
    def _fetch_battery_status(self) -> None:
        """Fetch battery status directly from the board controller.
        
        Requests battery info from the controller and updates widget state.
        Also updates board.chargerconnected and board.batterylevel globals
        for use by eventsThread (timeout hold on charger).
        Only requests a display update if values have changed.
        """
        try:
            from DGTCentaurMods.board.sync_centaur import command
            from DGTCentaurMods.board import board
            
            controller = board.controller
            if controller is None:
                return
            
            resp = controller.request_response(command.DGT_SEND_BATTERY_INFO)
            if resp is None or len(resp) == 0:
                return
            
            val = resp[0]
            new_level = val & 0x1F
            new_charger = ((val >> 5) & 0x07) in (1, 2)
            
            # Update board globals for eventsThread timeout hold logic
            board.batterylevel = new_level
            board.chargerconnected = 1 if new_charger else 0
            
            changed = False
            if self.level != new_level:
                self.level = new_level
                changed = True
            if self.charger_connected != new_charger:
                self.charger_connected = new_charger
                changed = True
            
            if changed:
                log.debug(f"Battery status changed: level={self.level}, charger={self.charger_connected}")
                self._last_rendered = None
                self.request_update(full=False)
                
        except Exception as e:
            log.debug(f"Error fetching battery status: {e}")
    
    def set_level(self, level: int) -> None:
        """Set battery level (0-20, where 20 is fully charged)."""
        if self.level != level:
            self.level = max(0, min(20, level))
            self._last_rendered = None
            self.request_update(full=False)
    
    def set_charger_connected(self, connected: bool) -> None:
        """Set charger connection status."""
        if self.charger_connected != connected:
            self.charger_connected = connected
            self._last_rendered = None
            self.request_update(full=False)
    
    def _get_battery_icon(self) -> Image.Image:
        """Get battery icon bitmap based on current battery state."""
        if not self._use_bitmap_icons:
            return self._render_drawn_battery()
        
        try:
            batterylevel = self.level if self.level is not None else 10
            chargerconnected = self.charger_connected
            
            indicator = "battery1"
            if batterylevel >= 18:
                indicator = "battery4"
            elif batterylevel >= 12:
                indicator = "battery3"
            elif batterylevel >= 6:
                indicator = "battery2"
            
            if chargerconnected:
                indicator = "batteryc"
                if batterylevel == 20:
                    indicator = "batterycf"
            
            path = AssetManager.get_resource_path(f"{indicator}.bmp")
            return Image.open(path)
        except Exception as e:
            log.error(f"Failed to load battery icon: {e}")
            return Image.new("1", (16, 16), 255)
    
    def _render_drawn_battery(self) -> Image.Image:
        """Render battery using drawing (fallback method)."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Convert level from 0-20 to 0-100 for display
        level_percent = (self.level / 20.0 * 100) if self.level is not None else 75
        
        # Battery outline
        draw.rectangle([2, 4, 26, 12], outline=0, width=1)
        draw.rectangle([26, 6, 28, 10], fill=0)
        
        # Battery level
        fill_width = int((level_percent / 100) * 22)
        if fill_width > 0:
            draw.rectangle([3, 5, 3 + fill_width, 11], fill=0)
        
        return img
    
    def render(self) -> Image.Image:
        """Render battery indicator."""
        if self._use_bitmap_icons:
            return self._get_battery_icon()
        else:
            return self._render_drawn_battery()
