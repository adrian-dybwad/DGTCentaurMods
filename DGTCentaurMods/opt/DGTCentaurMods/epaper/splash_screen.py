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
    from DGTCentaurMods.managers import AssetManager
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
    
    def __init__(self, message: str = "Press [OK]", background_shade: int = 4,
                 leave_room_for_status_bar: bool = True):
        """Initialize splash screen widget.
        
        Args:
            message: Initial message to display
            background_shade: Dithered background shade 0-16 (default 4 = ~25% grey)
            leave_room_for_status_bar: If True, start below status bar; if False, use full screen
        """
        if leave_room_for_status_bar:
            y_pos = STATUS_BAR_HEIGHT
            height = 296 - STATUS_BAR_HEIGHT
        else:
            y_pos = 0
            height = 296
        super().__init__(0, y_pos, 128, height, background_shade=background_shade)
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
        """Load knight logo image and fonts."""
        # Load the knight logo bitmap
        try:
            logo_path = AssetManager.get_resource_path("knight_logo.bmp")
            full_logo = Image.open(logo_path)
            # Resize to target size (use LANCZOS for older Pillow compatibility)
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS  # Pillow < 9.1.0
            self._logo = full_logo.resize(
                (self.LOGO_SIZE, self.LOGO_SIZE), 
                resample
            )
            # Ensure it's in mode '1'
            if self._logo.mode != '1':
                self._logo = self._logo.convert('1')
            
            # Create mask where black pixels (knight) are opaque, white is transparent
            # In mode '1': 0=black, 255=white
            # For mask: 255=opaque, 0=transparent
            self._logo_mask = Image.new("1", self._logo.size, 0)
            logo_pixels = self._logo.load()
            mask_pixels = self._logo_mask.load()
            for y in range(self._logo.height):
                for x in range(self._logo.width):
                    if logo_pixels[x, y] == 0:  # Black pixel in logo
                        mask_pixels[x, y] = 255  # Opaque in mask
        except Exception as e:
            log.error(f"Failed to load knight logo: {e}")
            # Create a simple placeholder
            self._logo = Image.new("1", (self.LOGO_SIZE, self.LOGO_SIZE), 255)
            self._logo_mask = None
        
        # Load fonts for "UNIVERSAL" text
        try:
            font_path = AssetManager.get_resource_path("Font.ttc")
            self._font = ImageFont.truetype(font_path, 16)
            self._font_large = ImageFont.truetype(font_path, 24)
        except Exception as e:
            log.debug(f"Failed to load font, using default: {e}")
            self._font = ImageFont.load_default()
            self._font_large = self._font
    
    def render(self) -> Image.Image:
        """Render the splash screen with knight logo, UNIVERSAL text, and message."""
        img = self.create_background_image()
        draw = ImageDraw.Draw(img)
        
        # Draw knight logo centered horizontally with transparency
        logo_x = (self.width - self.LOGO_SIZE) // 2
        if self._logo_mask:
            img.paste(self._logo, (logo_x, self.LOGO_Y), self._logo_mask)
        else:
            img.paste(self._logo, (logo_x, self.LOGO_Y))
        
        # Draw "UNIVERSAL" text centered with larger font
        universal_text = "UNIVERSAL"
        bbox = draw.textbbox((0, 0), universal_text, font=self._font_large)
        text_width = bbox[2] - bbox[0]
        x = (self.width - text_width) // 2
        draw.text((x, self.UNIVERSAL_Y), universal_text, font=self._font_large, fill=0)
        
        # Render message widget and paste with mask for transparency
        text_img = self._text_widget.render()
        text_mask = self._text_widget.get_mask()
        if text_mask:
            img.paste(text_img, (self.TEXT_MARGIN, self.TEXT_Y), text_mask)
        else:
            img.paste(text_img, (self.TEXT_MARGIN, self.TEXT_Y))
        
        return img
