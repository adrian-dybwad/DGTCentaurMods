"""
Splash screen widget displayed on startup.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
from .text import TextWidget, Justify
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
    """Splash screen widget with logo and updateable centered message.
    
    The message can be updated after creation using set_message().
    Text is automatically centered horizontally using TextWidget with Justify.CENTER.
    """
    
    def __init__(self, message: str = "Press [OK]"):
        super().__init__(0, STATUS_BAR_HEIGHT, 128, 296 - STATUS_BAR_HEIGHT)  # Full screen widget
        self.message = message
        self._logo = None
        self._load_resources()
        
        # Create a TextWidget for the message with centered justification
        self._text_widget = TextWidget(
            x=0, y=180, width=self.width, height=24,
            text=message, font_size=18, justify=Justify.CENTER
        )
    
    def set_message(self, message: str):
        """Update the splash screen message and trigger a re-render.
        
        Args:
            message: New message to display (will be centered)
        """
        self.message = message
        self._text_widget.text = message
        self.request_update(full=False)

    def _load_resources(self):
        """Load logo image."""
        try:
            self._logo = Image.open(AssetManager.get_resource_path("logo_mods_screen.jpg"))
        except Exception as e:
            log.error(f"Failed to load splash screen logo: {e}")
            self._logo = Image.new("1", (128, 128), 255)
    
    def render(self) -> Image.Image:
        """Render the splash screen with logo and centered text."""
        img = Image.new("1", (self.width, self.height), 255)
        
        # Draw logo
        img.paste(self._logo, (0, 0))
        
        # Render text widget and paste at position
        text_img = self._text_widget.render()
        img.paste(text_img, (0, 180))
        
        return img
