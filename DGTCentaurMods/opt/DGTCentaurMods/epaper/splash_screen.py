"""
Splash screen widget displayed on startup.

Displays the knight logo with "UNIVERSAL" text below,
and an updateable message at the bottom.
"""

from PIL import Image
from .framework.widget import Widget
from .text import TextWidget, Justify
from .status_bar import STATUS_BAR_HEIGHT
from typing import Optional, Tuple

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# Module-level knight logo and mask, set by application at startup
_knight_logo: Optional[Tuple[Image.Image, Image.Image]] = None


def set_knight_logo(logo: Image.Image, mask: Image.Image) -> None:
    """Set the module-level knight logo and mask.
    
    Called once at application startup to provide the logo.
    
    Args:
        logo: PIL Image of the knight logo
        mask: PIL Image mask for transparency
    """
    global _knight_logo
    _knight_logo = (logo, mask)


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
                 leave_room_for_status_bar: bool = True,
                 logo: Image.Image = None, logo_mask: Image.Image = None):
        """Initialize splash screen widget.
        
        Args:
            message: Initial message to display
            background_shade: Dithered background shade 0-16 (default 4 = ~25% grey)
            leave_room_for_status_bar: If True, start below status bar; if False, use full screen
            logo: Optional knight logo image. If None, uses module-level logo.
            logo_mask: Optional mask for logo transparency.
        """
        if leave_room_for_status_bar:
            y_pos = STATUS_BAR_HEIGHT
            height = 296 - STATUS_BAR_HEIGHT
        else:
            y_pos = 0
            height = 296
        super().__init__(0, y_pos, 128, height, background_shade=background_shade)
        self.message = message
        
        # Use provided logo or module-level logo
        if logo is not None:
            self._logo = logo
            self._logo_mask = logo_mask
        elif _knight_logo is not None:
            self._logo, self._logo_mask = _knight_logo
        else:
            log.error("No knight logo provided and none set at module level")
            self._logo = Image.new("1", (self.LOGO_SIZE, self.LOGO_SIZE), 255)
            self._logo_mask = None
        
        # Calculate text widget dimensions with margins for centering
        text_width = self.width - (self.TEXT_MARGIN * 2)
        
        # Create a TextWidget for "UNIVERSAL" title with centered justification
        self._universal_text = TextWidget(
            x=0, y=0, width=self.width, height=28,
            text="UNIVERSAL", font_size=24, justify=Justify.CENTER, transparent=True
        )
        
        # Create a TextWidget for the message with centered justification and wrapping
        self._text_widget = TextWidget(
            x=0, y=0, width=text_width, height=self.TEXT_HEIGHT,
            text=message, font_size=18, justify=Justify.CENTER, wrapText=True
        )
    
    def set_message(self, message: str):
        """Update the splash screen message and trigger a re-render.
        
        Only requests a display update if the message actually changes.
        Also logs the message prominently for startup visibility.
        
        Args:
            message: New message to display (will be centered)
        """
        if message == self.message:
            return
        self.message = message
        self._text_widget.set_text(message)
        
        # Log prominently so startup messages are visible in logs
        log.info("=" * 60)
        log.info(f"[Startup] {message}")
        log.info("=" * 60)
        
        self.request_update(full=False)
    
    def draw_on(self, img: Image.Image, draw_x: int, draw_y: int) -> None:
        """Draw the splash screen with knight logo, UNIVERSAL text, and message.
        
        Uses TextWidget for all text rendering.
        """
        # Draw dithered background
        self.draw_background(img, draw_x, draw_y)
        
        # Draw knight logo centered horizontally with transparency
        logo_x = draw_x + (self.width - self.LOGO_SIZE) // 2
        if self._logo_mask:
            img.paste(self._logo, (logo_x, draw_y + self.LOGO_Y), self._logo_mask)
        else:
            img.paste(self._logo, (logo_x, draw_y + self.LOGO_Y))
        
        # Draw "UNIVERSAL" text directly onto the background
        self._universal_text.draw_on(img, draw_x, draw_y + self.UNIVERSAL_Y)
        
        # Draw message text directly onto the background
        self._text_widget.draw_on(img, draw_x + self.TEXT_MARGIN, draw_y + self.TEXT_Y)
