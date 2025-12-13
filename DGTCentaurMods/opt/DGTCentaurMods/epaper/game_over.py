"""
Game over widget displaying winner, termination reason, and final times.

This widget replaces the clock widget at game end (y=200, height=56).
The analysis widget is repositioned below it (y=256, h=40) to show the
evaluation history graph. Together they fill the space below the board.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
import os
import sys
from typing import Optional, Tuple

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
    Widget displaying game over information.
    
    Replaces the clock widget at game end (y=200, h=56). Shows winner,
    termination reason, move count, and final times. The analysis widget
    is repositioned below (y=256, h=40) to show the evaluation history graph.
    """
    
    # Default position: replaces clock widget with expanded height
    DEFAULT_Y = 200
    DEFAULT_HEIGHT = 56
    
    def __init__(self, x: int = 0, y: int = None, width: int = 128, height: int = None):
        """
        Initialize game over widget.
        
        Args:
            x: X position (default 0)
            y: Y position (default 200, below board, replacing clock)
            width: Widget width (default 128)
            height: Widget height (default 36)
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
        self.white_time: Optional[int] = None  # Final white time in seconds
        self.black_time: Optional[int] = None  # Final black time in seconds
        
        self._font_large = self._load_font(16)
        self._font_medium = self._load_font(12)
        self._font_small = self._load_font(10)
    
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
    
    def set_result(self, result: str, termination: str = None, move_count: int = 0,
                   final_times: Optional[Tuple[int, int]] = None) -> None:
        """
        Set the game result and termination type.
        
        Args:
            result: Game result string ("1-0", "0-1", "1/2-1/2")
            termination: Termination type (e.g., "CHECKMATE", "STALEMATE", "RESIGN")
            move_count: Number of moves played in the game
            final_times: Optional tuple of (white_seconds, black_seconds) for timed games
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
        
        if final_times is not None:
            white_time, black_time = final_times
            if self.white_time != white_time or self.black_time != black_time:
                self.white_time = white_time
                self.black_time = black_time
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
        
        # Convert to readable format - use short forms for compact display
        termination_map = {
            "CHECKMATE": "Checkmate",
            "STALEMATE": "Stalemate",
            "INSUFFICIENT_MATERIAL": "Insuff. material",
            "SEVENTYFIVE_MOVES": "75-move rule",
            "FIVEFOLD_REPETITION": "5x repetition",
            "FIFTY_MOVES": "50-move rule",
            "THREEFOLD_REPETITION": "3x repetition",
            "RESIGN": "Resignation",
            "TIMEOUT": "Time forfeit",
            "ABANDONED": "Abandoned",
        }
        
        return termination_map.get(term.upper(), term.title())
    
    def _format_time(self, seconds: int) -> str:
        """
        Format time in seconds to display string.
        
        Args:
            seconds: Time in seconds
            
        Returns:
            Formatted time string (M:SS or MM:SS)
        """
        if seconds <= 0:
            return "0:00"
        
        minutes = seconds // 60
        secs = seconds % 60
        
        return f"{minutes}:{secs:02d}"
    
    def render(self) -> Image.Image:
        """
        Render game over widget.
        
        Layout (56 pixels height):
        - Line 1 (y=2): Winner (e.g., "White wins", "Black wins", "Draw")
        - Line 2 (y=20): Termination reason (e.g., "Checkmate", "Resignation")
        - Line 3 (y=38): Move count and/or times (e.g., "42 moves  W:5:23 B:3:17")
        """
        if self._last_rendered is not None:
            return self._last_rendered
        
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Draw separator line at top
        draw.line([(0, 0), (self.width, 0)], fill=0, width=1)
        
        # Line 1: Winner (centered, large font)
        if self.winner:
            winner_bbox = draw.textbbox((0, 0), self.winner, font=self._font_large)
            winner_width = winner_bbox[2] - winner_bbox[0]
            winner_x = (self.width - winner_width) // 2
            draw.text((winner_x, 2), self.winner, font=self._font_large, fill=0)
        
        # Line 2: Termination reason (centered, medium font)
        if self.termination:
            term_bbox = draw.textbbox((0, 0), self.termination, font=self._font_medium)
            term_width = term_bbox[2] - term_bbox[0]
            term_x = (self.width - term_width) // 2
            draw.text((term_x, 20), self.termination, font=self._font_medium, fill=0)
        
        # Line 3: Move count and/or times (centered, small font)
        line3_parts = []
        
        if self.move_count > 0:
            line3_parts.append(f"{self.move_count} moves")
        
        if self.white_time is not None and self.black_time is not None:
            white_str = self._format_time(self.white_time)
            black_str = self._format_time(self.black_time)
            line3_parts.append(f"W:{white_str} B:{black_str}")
        
        if line3_parts:
            line3 = "  ".join(line3_parts)
            line3_bbox = draw.textbbox((0, 0), line3, font=self._font_small)
            line3_width = line3_bbox[2] - line3_bbox[0]
            line3_x = (self.width - line3_width) // 2
            draw.text((line3_x, 38), line3, font=self._font_small, fill=0)
        
        self._last_rendered = img
        return img
