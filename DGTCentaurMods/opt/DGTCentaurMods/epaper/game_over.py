"""
Game over widget displaying winner and termination reason.

This widget occupies the space below the analysis widget (y=224, height=72)
and displays the game result information without including the analysis widget.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
import os
import sys

# Import AssetManager - use direct module import to avoid circular import
try:
    from DGTCentaurMods.managers.asset import AssetManager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from managers.asset import AssetManager
    except ImportError:
        AssetManager = None


class GameOverWidget(Widget):
    """
    Widget displaying game over information below the analysis widget.
    
    Shows winner, termination reason, and game result in a compact format
    designed for the 128x72 pixel space below the analysis widget.
    """
    
    # Default position: below analysis widget (y=224) with height=72
    DEFAULT_Y = 224
    DEFAULT_HEIGHT = 72
    
    def __init__(self, x: int = 0, y: int = None, width: int = 128, height: int = None):
        """
        Initialize game over widget.
        
        Args:
            x: X position (default 0)
            y: Y position (default 224, below analysis widget)
            width: Widget width (default 128)
            height: Widget height (default 72)
        """
        if y is None:
            y = self.DEFAULT_Y
        if height is None:
            height = self.DEFAULT_HEIGHT
            
        super().__init__(x, y, width, height)
        
        self.result = ""           # "1-0", "0-1", "1/2-1/2"
        self.winner = ""           # "White wins", "Black wins", "Draw"
        self.termination = ""      # "Checkmate", "Stalemate", "Resignation", etc.
        self.move_count = 0        # Number of moves played
        
        self._font_large = self._load_font(16)
        self._font_small = self._load_font(12)
    
    def _load_font(self, size: int):
        """Load font with Font.ttc as default."""
        if AssetManager is not None:
            try:
                font_path = AssetManager.get_resource_path("Font.ttc")
                if font_path and os.path.exists(font_path):
                    return ImageFont.truetype(font_path, size)
            except Exception:
                pass
        
        # Fallback paths
        font_paths = [
            '/opt/DGTCentaurMods/resources/Font.ttc',
            'resources/Font.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()
    
    def set_result(self, result: str, termination: str = None, move_count: int = 0) -> None:
        """
        Set the game result and termination type.
        
        Args:
            result: Game result string ("1-0", "0-1", "1/2-1/2")
            termination: Termination type (e.g., "CHECKMATE", "STALEMATE", "RESIGN")
            move_count: Number of moves played in the game
        """
        changed = False
        
        if self.result != result:
            self.result = result
            changed = True
            
            # Determine winner from result
            if result == "1-0":
                self.winner = "White wins"
            elif result == "0-1":
                self.winner = "Black wins"
            elif result == "1/2-1/2":
                self.winner = "Draw"
            else:
                self.winner = result
        
        if termination is not None and self.termination != termination:
            # Format termination for display
            self.termination = self._format_termination(termination)
            changed = True
        
        if move_count > 0 and self.move_count != move_count:
            self.move_count = move_count
            changed = True
        
        if changed:
            self._last_rendered = None
            self.request_update(full=False)
    
    def _format_termination(self, termination: str) -> str:
        """
        Format termination type for display.
        
        Args:
            termination: Raw termination string (e.g., "CHECKMATE", "Termination.CHECKMATE")
            
        Returns:
            Formatted display string
        """
        if not termination:
            return ""
        
        # Remove "Termination." prefix if present
        term = termination.replace("Termination.", "")
        
        # Convert to readable format
        termination_map = {
            "CHECKMATE": "Checkmate",
            "STALEMATE": "Stalemate",
            "INSUFFICIENT_MATERIAL": "Insufficient material",
            "SEVENTYFIVE_MOVES": "75-move rule",
            "FIVEFOLD_REPETITION": "5-fold repetition",
            "FIFTY_MOVES": "50-move rule",
            "THREEFOLD_REPETITION": "3-fold repetition",
            "RESIGN": "Resignation",
            "TIMEOUT": "Time forfeit",
            "ABANDONED": "Abandoned",
        }
        
        return termination_map.get(term.upper(), term.title())
    
    def render(self) -> Image.Image:
        """
        Render game over widget.
        
        Layout (72 pixels height):
        - Line 1 (y=2): "GAME OVER" header
        - Line 2 (y=20): Winner ("White wins", "Black wins", "Draw")
        - Line 3 (y=38): Termination reason
        - Line 4 (y=56): Move count (if available)
        """
        if self._last_rendered is not None:
            return self._last_rendered
        
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Draw separator line at top
        draw.line([(0, 0), (self.width, 0)], fill=0, width=1)
        
        # Line 1: "GAME OVER" header (centered)
        header = "GAME OVER"
        header_bbox = draw.textbbox((0, 0), header, font=self._font_large)
        header_width = header_bbox[2] - header_bbox[0]
        header_x = (self.width - header_width) // 2
        draw.text((header_x, 2), header, font=self._font_large, fill=0)
        
        # Line 2: Winner (centered)
        if self.winner:
            winner_bbox = draw.textbbox((0, 0), self.winner, font=self._font_large)
            winner_width = winner_bbox[2] - winner_bbox[0]
            winner_x = (self.width - winner_width) // 2
            draw.text((winner_x, 20), self.winner, font=self._font_large, fill=0)
        
        # Line 3: Termination reason (centered)
        if self.termination:
            term_bbox = draw.textbbox((0, 0), self.termination, font=self._font_small)
            term_width = term_bbox[2] - term_bbox[0]
            term_x = (self.width - term_width) // 2
            draw.text((term_x, 40), self.termination, font=self._font_small, fill=0)
        
        # Line 4: Move count if available (centered)
        if self.move_count > 0:
            moves_text = f"{self.move_count} moves"
            moves_bbox = draw.textbbox((0, 0), moves_text, font=self._font_small)
            moves_width = moves_bbox[2] - moves_bbox[0]
            moves_x = (self.width - moves_width) // 2
            draw.text((moves_x, 56), moves_text, font=self._font_small, fill=0)
        
        self._last_rendered = img
        return img
