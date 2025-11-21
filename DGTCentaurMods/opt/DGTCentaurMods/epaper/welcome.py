"""
Welcome screen widget displayed on startup.
"""

from PIL import Image, ImageDraw, ImageFont
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


class WelcomeWidget(Widget):
    """Welcome screen widget with logo and press prompt."""
    
    def __init__(self, status_text: str = "READY"):
        super().__init__(0, 0, 128, 296)  # Full screen widget
        self.status_text = status_text
        self._font_18 = None
        self._status_font = None
        self._logo = None
        self._battery_icon = None
        self._load_resources()
    
    def _load_resources(self):
        """Load fonts and images."""
        try:
            self._font_18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
            self._status_font = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 14)
            self._logo = Image.open(AssetManager.get_resource_path("logo_mods_screen.jpg"))
        except Exception as e:
            log.error(f"Failed to load welcome widget resources: {e}")
            self._font_18 = ImageFont.load_default()
            self._status_font = ImageFont.load_default()
            self._logo = Image.new("1", (128, 128), 255)
    
    def set_status_text(self, status_text: str) -> None:
        """Update the status text."""
        self.status_text = status_text
        self._last_rendered = None  # Force re-render
    
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
        """Render the welcome screen."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        STATUS_BAR_HEIGHT = 16
        
        # Draw status bar
        draw.rectangle([0, 0, 128, STATUS_BAR_HEIGHT], fill=255, outline=255)
        draw.text((2, -1), self.status_text, font=self._status_font, fill=0)
        
        # Draw battery icon
        battery_icon = self._get_battery_icon()
        img.paste(battery_icon, (98, 1))
        
        # Draw welcome content
        draw.rectangle([0, STATUS_BAR_HEIGHT, 128, 296], fill=255, outline=255)
        img.paste(self._logo, (0, STATUS_BAR_HEIGHT + 4))
        draw.text((0, STATUS_BAR_HEIGHT + 180), "   Press [>||]", font=self._font_18, fill=0)
        
        return img

