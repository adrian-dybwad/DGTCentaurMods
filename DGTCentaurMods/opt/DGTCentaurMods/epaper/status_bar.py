"""
Status bar widget displaying time and battery icon.
"""

from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
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


class StatusBarWidget(Widget):
    """Status bar widget displaying time and battery icon."""
    
    def __init__(self, x: int = 0, y: int = 0):
        super().__init__(x, y, 128, 16)
        self._font = self._load_font()
    
    def _load_font(self):
        """Load font with fallbacks."""
        font_paths = [
            '/opt/DGTCentaurMods/resources/Font.ttc',
            'resources/Font.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, 14)
                except:
                    pass
        return ImageFont.load_default()
    
    def _get_battery_icon(self) -> Image.Image:
        """Get battery icon based on current battery state."""
        try:
            from DGTCentaurMods.board import board
            indicator = "battery1"
            if board.batterylevel >= 18:
                indicator = "battery4"
            elif board.batterylevel >= 12:
                indicator = "battery3"
            elif board.batterylevel >= 6:
                indicator = "battery2"
            if board.chargerconnected > 0:
                indicator = "batteryc"
                if board.batterylevel == 20:
                    indicator = "batterycf"
            path = AssetManager.get_resource_path(f"{indicator}.bmp")
            return Image.open(path)
        except Exception as e:
            log.error(f"Failed to load battery icon: {e}")
            return Image.new("1", (16, 16), 255)
    
    def render(self) -> Image.Image:
        """Render status bar with time and battery icon."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Draw time (HH:MM format)
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        draw.text((2, -1), time_str, font=self._font, fill=0)
        
        # Draw battery icon
        battery_icon = self._get_battery_icon()
        img.paste(battery_icon, (98, 1))
        
        return img

