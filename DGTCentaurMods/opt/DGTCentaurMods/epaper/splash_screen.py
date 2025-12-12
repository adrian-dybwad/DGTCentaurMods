"""
Splash screen widget displayed on startup.

Displays a modified DGT Centaur logo with "UNIVERSAL" replacing "MODS",
and an updateable message below.
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
    
    The logo is cropped to remove the "MODS" text, and "UNIVERSAL" is drawn
    dynamically in a smaller font to fit the width.
    
    The message can be updated after creation using set_message().
    Text is automatically centered horizontally using TextWidget with Justify.CENTER.
    Supports multi-line text with wrapping.
    
    This is a modal widget - when present, only this widget is rendered.
    """
    
    # SplashScreen is modal - when present, only it is rendered
    is_modal = True
    
    # Layout configuration
    LOGO_CROP_HEIGHT = 130  # Crop logo to this height to remove "MODS" text
    UNIVERSAL_Y = 132  # Y position for "UNIVERSAL" text
    TEXT_MARGIN = 4  # Margin on each side
    TEXT_Y = 170  # Y position for message text (below logo)
    TEXT_HEIGHT = 88  # Height for 4 lines of text at font size 18
    
    def __init__(self, message: str = "Press [OK]", background_shade: int = 4):
        """Initialize splash screen widget.
        
        Args:
            message: Initial message to display
            background_shade: Dithered background shade 0-16 (default 4 = ~25% grey)
        """
        super().__init__(0, STATUS_BAR_HEIGHT, 128, 296 - STATUS_BAR_HEIGHT, background_shade=background_shade)
        self.message = message
        self._logo = None
        self._font = None
        self._load_resources()
        
        # Calculate text widget dimensions with margins for centering
        text_width = self.width - (self.TEXT_MARGIN * 2)
        
        # Create a TextWidget for the message with centered justification and wrapping
        self._text_widget = TextWidget(
            x=0, y=0, width=text_width, height=self.TEXT_HEIGHT,
            text=message, font_size=18, justify=Justify.CENTER, wrapText=True
        )
    
    def set_message(self, message: str):
        """Update the splash screen message and trigger a re-render.
        
        Only requests a display update if the message actually changes.
        
        Args:
            message: New message to display (will be centered)
        """
        if message == self.message:
            return
        self.message = message
        self._text_widget.text = message
        self.request_update(full=False)

    def _load_resources(self):
        """Load logo image and font."""
        # Load logo and crop to remove "MODS" text
        try:
            full_logo = Image.open(AssetManager.get_resource_path("logo_mods_screen.jpg"))
            # Crop to remove the "MODS" text at the bottom
            self._logo = full_logo.crop((0, 0, full_logo.width, self.LOGO_CROP_HEIGHT))
        except Exception as e:
            log.error(f"Failed to load splash screen logo: {e}")
            self._logo = Image.new("1", (128, self.LOGO_CROP_HEIGHT), 255)
        
        # Load font for "UNIVERSAL" text
        try:
            font_path = AssetManager.get_resource_path("Font.ttc")
            self._font = ImageFont.truetype(font_path, 16)
        except Exception as e:
            log.debug(f"Failed to load font, using default: {e}")
            self._font = ImageFont.load_default()
    
    def render(self) -> Image.Image:
        """Render the splash screen with logo, UNIVERSAL text, and message."""
        img = self.create_background_image()
        draw = ImageDraw.Draw(img)
        
        # Draw cropped logo (without "MODS")
        img.paste(self._logo, (0, 0))
        
        # Draw "UNIVERSAL" text centered
        universal_text = "UNIVERSAL"
        bbox = draw.textbbox((0, 0), universal_text, font=self._font)
        text_width = bbox[2] - bbox[0]
        x = (self.width - text_width) // 2
        draw.text((x, self.UNIVERSAL_Y), universal_text, font=self._font, fill=0)
        
        # Render message widget and paste centered horizontally
        text_img = self._text_widget.render()
        img.paste(text_img, (self.TEXT_MARGIN, self.TEXT_Y))
        
        return img
