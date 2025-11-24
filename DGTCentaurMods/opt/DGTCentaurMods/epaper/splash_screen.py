"""
Splash screen widget displayed on startup.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
from .status_bar import STATUS_BAR_HEIGHT
import os
import sys

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


class SplashScreen(Widget):
    """Splash screen widget with logo and press prompt."""
    
    def __init__(self, message: str = "   Press [✓]"):
        super().__init__(0, STATUS_BAR_HEIGHT, 128, 296 - STATUS_BAR_HEIGHT)  # Full screen widget
        self.message = message
        self._font_18 = None
        self._logo = None
        self._load_resources()

    def _load_resources(self):
        """Load fonts and images."""
        try:
            self._font_18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
            self._logo = Image.open(AssetManager.get_resource_path("logo_mods_screen.jpg"))
        except Exception as e:
            log.error(f"Failed to load splash screen resources: {e}")
            self._font_18 = ImageFont.load_default()
            self._logo = Image.new("1", (128, 128), 255)
    
    def render(self) -> Image.Image:
        """Render the splash screen."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        draw.rectangle([0, 0, self.width, self.height], fill=255, outline=255)
        img.paste(self._logo, (0, 0))
        draw.text((0, 180), self.message, font=self._font_18, fill=0)
        
        return img
