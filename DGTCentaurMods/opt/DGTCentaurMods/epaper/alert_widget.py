"""
Alert widget for displaying CHECK and QUEEN threat warnings.

Displays a prominent alert with:
- CHECK: When a king is in check, with background color of the side in check
- YOUR QUEEN: When a queen is under attack, with background color of the threatened queen

The widget also triggers LED flashing from the attacking piece to the threatened piece.
Uses TextWidget for all text rendering.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
from .text import TextWidget, Justify

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
    
    Uses TextWidget for text rendering.
    Attacker/target squares trigger LED flashing from attacker to target.
    """
    
    # Alert types
    ALERT_CHECK = "check"
    ALERT_QUEEN = "queen"
    ALERT_HINT = "hint"
    
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
        self._alert_type = None  # "check", "queen", or "hint"
        self._is_black_threatened = False  # True if black piece is threatened
        self._attacker_square = None  # Square index (0-63) of attacking piece
        self._target_square = None  # Square index (0-63) of threatened piece
        self._hint_text_value = ""  # Hint move text (e.g., "e2e4")
        self.visible = False  # Hidden by default (uses base class attribute)
        
        # Create TextWidgets for CHECK and YOUR QUEEN
        # CHECK: single large centered text
        self._check_text = TextWidget(x=0, y=0, width=width, height=height,
                                       text="CHECK", font_size=32,
                                       justify=Justify.CENTER, transparent=True)
        # YOUR QUEEN: two lines centered - use wrap text
        self._queen_text = TextWidget(x=0, y=0, width=width, height=height,
                                       text="YOUR\nQUEEN", font_size=18,
                                       justify=Justify.CENTER, wrapText=True,
                                       transparent=True)
        # HINT: shows the suggested move
        self._hint_text = TextWidget(x=0, y=0, width=width, height=height,
                                      text="", font_size=28,
                                      justify=Justify.CENTER, transparent=True)
    
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
        
        log.info(f"[AlertWidget] Showing CHECK: {'black' if is_black_in_check else 'white'} king in check, attacker={attacker_square}, king={king_square}")
        
        # Flash LEDs from attacker to king
        self._flash_leds()
        
        # Use base class show() to handle visibility and update
        super().show()
    
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
        
        log.info(f"[AlertWidget] Showing QUEEN threat: {'black' if is_black_queen_threatened else 'white'} queen threatened, attacker={attacker_square}, queen={queen_square}")
        
        # Flash LEDs from attacker to queen
        self._flash_leds()
        
        # Use base class show() to handle visibility and update
        super().show()
    
    def show_hint(self, move_text: str, from_square: int, to_square: int) -> None:
        """Show move hint with the suggested move.
        
        Args:
            move_text: Move in readable format (e.g., "e2e4" or "Nf3")
            from_square: Square index (0-63) of the piece to move
            to_square: Square index (0-63) of the target square
        """
        self._alert_type = self.ALERT_HINT
        self._hint_text_value = move_text
        self._attacker_square = from_square
        self._target_square = to_square
        self._is_black_threatened = False  # Not used for hints
        
        log.info(f"[AlertWidget] Showing HINT: {move_text} ({from_square} -> {to_square})")
        
        # Flash LEDs from source to target
        self._flash_leds()
        
        # Use base class show() to handle visibility and update
        super().show()
    
    def hide(self) -> None:
        """Hide the alert widget and clear alert state."""
        if self.visible:
            self._alert_type = None
            self._attacker_square = None
            self._target_square = None
            log.info("[AlertWidget] Hiding alert")
            # Use base class hide() to handle visibility and update
            super().hide()
    
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
    
    
    def render(self) -> Image.Image:
        """Render alert widget using TextWidgets.
        
        Returns transparent (all white) image if not visible.
        Otherwise renders CHECK or YOUR QUEEN with appropriate colors.
        """
        img = Image.new("1", (self.width, self.height), 255)
        
        if not self.visible or self._alert_type is None:
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
            # Draw "CHECK" centered directly onto the background
            y_offset = (self.height - self._check_text.height) // 2
            self._check_text.draw_on(img, 0, y_offset, text_color=text_color)
            
        elif self._alert_type == self.ALERT_QUEEN:
            # Draw "YOUR\nQUEEN" centered directly onto the background
            self._queen_text.draw_on(img, 0, 0, text_color=text_color)
        
        elif self._alert_type == self.ALERT_HINT:
            # Draw hint move text centered - always white bg, black text
            draw.rectangle([(0, 0), (self.width - 1, self.height - 1)], fill=255, outline=0)
            self._hint_text.set_text(self._hint_text_value)
            y_offset = (self.height - self._hint_text.height) // 2
            self._hint_text.draw_on(img, 0, y_offset, text_color=0)
        
        return img
