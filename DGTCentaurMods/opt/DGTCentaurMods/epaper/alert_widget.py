"""
Alert widget for displaying CHECK and QUEEN threat warnings.

Displays a prominent alert with:
- CHECK: When a king is in check, with background color of the side in check
- YOUR QUEEN: When a queen is under attack, with background color of the threatened queen

The widget also triggers LED flashing from the attacking piece to the threatened piece.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
import os
import sys

try:
    from DGTCentaurMods.managers import AssetManager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from asset_manager import AssetManager
    except ImportError:
        AssetManager = None

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class AlertWidget(Widget):
    """Widget displaying CHECK or QUEEN threat alerts with LED flashing.
    
    Background color indicates which side is threatened:
    - Black background (white text) = Black piece is threatened
    - White background (black text) = White piece is threatened
    
    Attacker/target squares trigger LED flashing from attacker to target.
    """
    
    # Alert types
    ALERT_CHECK = "check"
    ALERT_QUEEN = "queen"
    
    def __init__(self, x: int = 0, y: int = 144, width: int = 128, height: int = 40):
        """
        Initialize alert widget.
        
        Args:
            x: X position
            y: Y position (default 144 = below chess board at y=16+128)
            width: Widget width
            height: Widget height
        """
        super().__init__(x, y, width, height)
        self._alert_type = None  # "check" or "queen"
        self._is_black_threatened = False  # True if black piece is threatened
        self._attacker_square = None  # Square index (0-63) of attacking piece
        self._target_square = None  # Square index (0-63) of threatened piece
        self._visible = False
        self._font_check = None
        self._font_queen = None
        self._load_fonts()
    
    def _load_fonts(self):
        """Load fonts for CHECK and YOUR QUEEN text.
        
        CHECK uses a single large font, YOUR QUEEN uses smaller font for two lines.
        """
        font_path = None
        
        if AssetManager is not None:
            try:
                font_path = AssetManager.get_resource_path("Font.ttc")
            except Exception:
                pass
        
        if not font_path or not os.path.exists(font_path):
            # Fallback paths
            fallback_paths = [
                '/opt/DGTCentaurMods/resources/Font.ttc',
                'resources/Font.ttc',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            ]
            for path in fallback_paths:
                if os.path.exists(path):
                    font_path = path
                    break
        
        # Load CHECK font - as large as possible for height
        # Height is 40px, leave some margin for vertical centering
        try:
            if font_path:
                self._font_check = ImageFont.truetype(font_path, 32)
            else:
                self._font_check = ImageFont.load_default()
        except Exception:
            self._font_check = ImageFont.load_default()
        
        # Load YOUR QUEEN font - smaller for two lines
        # Each line needs to fit in roughly half the height
        try:
            if font_path:
                self._font_queen = ImageFont.truetype(font_path, 18)
            else:
                self._font_queen = ImageFont.load_default()
        except Exception:
            self._font_queen = ImageFont.load_default()
    
    def show_check(self, is_black_in_check: bool, attacker_square: int, king_square: int) -> None:
        """Show CHECK alert and flash LEDs.
        
        Args:
            is_black_in_check: True if black king is in check, False if white
            attacker_square: Square index (0-63) of the piece giving check
            king_square: Square index (0-63) of the king in check
        """
        self._alert_type = self.ALERT_CHECK
        self._is_black_threatened = is_black_in_check
        self._attacker_square = attacker_square
        self._target_square = king_square
        self._visible = True
        self._last_rendered = None
        
        log.info(f"[AlertWidget] Showing CHECK: {'black' if is_black_in_check else 'white'} king in check, attacker={attacker_square}, king={king_square}")
        
        # Flash LEDs from attacker to king
        self._flash_leds()
        
        self.request_update(full=False)
    
    def show_queen_threat(self, is_black_queen_threatened: bool, attacker_square: int, queen_square: int) -> None:
        """Show YOUR QUEEN alert and flash LEDs.
        
        Args:
            is_black_queen_threatened: True if black queen is threatened, False if white
            attacker_square: Square index (0-63) of the attacking piece
            queen_square: Square index (0-63) of the threatened queen
        """
        self._alert_type = self.ALERT_QUEEN
        self._is_black_threatened = is_black_queen_threatened
        self._attacker_square = attacker_square
        self._target_square = queen_square
        self._visible = True
        self._last_rendered = None
        
        log.info(f"[AlertWidget] Showing QUEEN threat: {'black' if is_black_queen_threatened else 'white'} queen threatened, attacker={attacker_square}, queen={queen_square}")
        
        # Flash LEDs from attacker to queen
        self._flash_leds()
        
        self.request_update(full=False)
    
    def hide(self) -> None:
        """Hide the alert widget."""
        if self._visible:
            self._visible = False
            self._alert_type = None
            self._attacker_square = None
            self._target_square = None
            self._last_rendered = None
            log.info("[AlertWidget] Hiding alert")
            self.request_update(full=False)
    
    def _flash_leds(self) -> None:
        """Flash LEDs from attacker square to target square."""
        if self._attacker_square is None or self._target_square is None:
            return
        
        try:
            # Import board module for LED control
            from DGTCentaurMods.board import board
            # Flash from attacker to target with repeat=0 (continuous until next LED command)
            board.ledFromTo(self._attacker_square, self._target_square, intensity=5, speed=3, repeat=0)
        except Exception as e:
            log.error(f"[AlertWidget] Error flashing LEDs: {e}")
    
    def is_visible(self) -> bool:
        """Check if alert is currently visible."""
        return self._visible
    
    def render(self) -> Image.Image:
        """Render alert widget.
        
        Returns transparent (all white) image if not visible.
        Otherwise renders CHECK or YOUR QUEEN with appropriate colors.
        """
        img = Image.new("1", (self.width, self.height), 255)
        
        if not self._visible or self._alert_type is None:
            return img
        
        draw = ImageDraw.Draw(img)
        
        # Determine colors based on which side is threatened
        # Black threatened = black background (fill=0), white text (fill=255)
        # White threatened = white background (fill=255), black text (fill=0)
        if self._is_black_threatened:
            bg_color = 0  # Black background
            text_color = 255  # White text
        else:
            bg_color = 255  # White background
            text_color = 0  # Black text
        
        # Draw background
        draw.rectangle([(0, 0), (self.width - 1, self.height - 1)], fill=bg_color, outline=0)
        
        if self._alert_type == self.ALERT_CHECK:
            # Draw "CHECK" centered, as large as possible
            text = "CHECK"
            font = self._font_check
            
            # Get text size for centering
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            x = (self.width - text_width) // 2
            y = (self.height - text_height) // 2 - 2  # Slight upward adjustment
            
            draw.text((x, y), text, font=font, fill=text_color)
            
        elif self._alert_type == self.ALERT_QUEEN:
            # Draw "YOUR" and "QUEEN" on two lines, centered
            font = self._font_queen
            
            # First line: "YOUR"
            text1 = "YOUR"
            bbox1 = draw.textbbox((0, 0), text1, font=font)
            text1_width = bbox1[2] - bbox1[0]
            text1_height = bbox1[3] - bbox1[1]
            
            # Second line: "QUEEN"
            text2 = "QUEEN"
            bbox2 = draw.textbbox((0, 0), text2, font=font)
            text2_width = bbox2[2] - bbox2[0]
            text2_height = bbox2[3] - bbox2[1]
            
            # Calculate vertical positioning for two lines
            total_text_height = text1_height + text2_height + 2  # 2px gap between lines
            start_y = (self.height - total_text_height) // 2
            
            # Draw first line
            x1 = (self.width - text1_width) // 2
            draw.text((x1, start_y), text1, font=font, fill=text_color)
            
            # Draw second line
            x2 = (self.width - text2_width) // 2
            draw.text((x2, start_y + text1_height + 2), text2, font=font, fill=text_color)
        
        return img
