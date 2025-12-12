"""
Splash screen widget displayed on startup.

Displays the knight logo with "UNIVERSAL" text below,
and an updateable message at the bottom.
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
    """Splash screen widget with knight logo and updateable centered message.
    
    Displays the knight logo centered at the top, with "UNIVERSAL" text below,
    and a customizable message at the bottom.
    
    The message can be updated after creation using set_message().
    Text is automatically centered horizontally using TextWidget with Justify.CENTER.
    Supports multi-line text with wrapping.
    
    This is a modal widget - when present, only this widget is rendered.
    """
    
    # SplashScreen is modal - when present, only it is rendered
    is_modal = True
    
    # Layout configuration
    LOGO_SIZE = 100  # Size of the knight logo
    LOGO_Y = 10  # Y position for logo (from top of widget)
    UNIVERSAL_Y = 120  # Y position for "UNIVERSAL" text
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
        self._font_large = None
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
        self._text_widget.set_text(message)
        self.request_update(full=False)

    def _load_resources(self):
        """Load logo image and font."""
        # Load logo and crop to remove "MODS" text
        try:
            full_logo = Image.open(AssetManager.get_resource_path("logo_mods_screen.jpg"))
            # Crop to remove the "MODS" text at the bottom
            cropped = full_logo.crop((0, 0, full_logo.width, self.LOGO_CROP_HEIGHT))
            # Convert to 1-bit for consistent processing
            self._logo = cropped.convert("1")
            # Create mask where non-white pixels are opaque (white in mask)
            # and white pixels are transparent (black in mask)
            self._logo_mask = Image.new("1", self._logo.size, 0)
            logo_pixels = self._logo.load()
            mask_pixels = self._logo_mask.load()
            for y in range(self._logo.height):
                for x in range(self._logo.width):
                    # If pixel is not white (i.e., it's part of the logo), make it opaque in mask
                    if logo_pixels[x, y] == 0:  # Black pixel in logo
                        mask_pixels[x, y] = 255  # Opaque in mask
        except Exception as e:
            log.error(f"Failed to load splash screen logo: {e}")
            self._logo = Image.new("1", (128, self.LOGO_CROP_HEIGHT), 255)
            self._logo_mask = None
        
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
        
        # Draw cropped logo with transparency (white pixels are transparent)
        if self._logo_mask:
            img.paste(self._logo, (0, 0), self._logo_mask)
        else:
            img.paste(self._logo, (0, 0))
        
        # Draw "UNIVERSAL" text centered
        universal_text = "UNIVERSAL"
        bbox = draw.textbbox((0, 0), universal_text, font=self._font)
        text_width = bbox[2] - bbox[0]
        x = (self.width - text_width) // 2
        draw.text((x, self.UNIVERSAL_Y), universal_text, font=self._font, fill=0)
        
        # Render message widget and paste with mask for transparency
        text_img = self._text_widget.render()
        text_mask = self._text_widget.get_mask()
        if text_mask:
            img.paste(text_img, (self.TEXT_MARGIN, self.TEXT_Y), text_mask)
        else:
            img.paste(text_img, (self.TEXT_MARGIN, self.TEXT_Y))
        
        return img
