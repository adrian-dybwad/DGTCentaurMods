"""
Battery level indicator widget.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
import os
import sys

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

try:
    from DGTCentaurMods.display.ui_components import AssetManager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from display.ui_components import AssetManager


class BatteryWidget(Widget):
    """Battery level indicator using bitmap icons."""
    
    def __init__(self, x: int, y: int, level: int = None, charger_connected: bool = False):
        super().__init__(x, y, 16, 16)
        self.level = level
        self.charger_connected = charger_connected
        self._use_bitmap_icons = True
    
    def set_level(self, level: int) -> None:
        """Set battery level (0-20, where 20 is fully charged)."""
        self.level = max(0, min(20, level))
    
    def set_charger_connected(self, connected: bool) -> None:
        """Set charger connection status."""
        self.charger_connected = connected
    
    def update_from_board(self) -> None:
        """Update battery level and charger status from board."""
        try:
            from DGTCentaurMods.board import board
            self.level = board.batterylevel
            self.charger_connected = board.chargerconnected > 0
        except Exception as e:
            log.debug(f"Error reading battery status from board: {e}")
    
    def _get_battery_icon(self) -> Image.Image:
        """Get battery icon bitmap based on current battery state."""
        if not self._use_bitmap_icons:
            # Fallback to drawn battery
            return self._render_drawn_battery()
        
        try:
            from DGTCentaurMods.board import board
            # Use board state if available, otherwise use widget state
            if board is not None:
                batterylevel = board.batterylevel
                chargerconnected = board.chargerconnected > 0
            else:
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
