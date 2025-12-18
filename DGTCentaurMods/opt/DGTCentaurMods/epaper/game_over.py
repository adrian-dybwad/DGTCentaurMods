"""
Game over widget displaying winner, termination reason, and final times.

This widget replaces the clock widget at game end (y=144, height=72).
The analysis widget stays in place (y=216, h=80) to show the
evaluation history graph.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
from .text import TextWidget, Justify
import os
import sys
import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)


class GameOverWidget(Widget):
    """
    Widget displaying game over information.
    
    Replaces the clock widget at game end (y=144, h=72). Shows winner,
    termination reason, move count, and final times using TextWidget.
    The analysis widget stays in place (y=216, h=80) to show the
    evaluation history graph.
    """
    
    # Default position: replaces clock widget (board ends at y=144)
    DEFAULT_Y = 144
    DEFAULT_HEIGHT = 72
    
    def __init__(self, x: int, y: int, width: int, height: int, update_callback):
        """
        Initialize game over widget.
        
        Args:
            x: X position
            y: Y position
            width: Widget width
            height: Widget height
            update_callback: Callback to trigger display updates. Must not be None.
        """
        super().__init__(x, y, width, height, update_callback)
        
        self.result = ""           # "1-0", "0-1", "1/2-1/2"
        self.winner = ""           # "White wins", "Black wins", "Draw"
        self.termination = ""      # "Checkmate", "Stalemate", "Resignation", etc.
        self.move_count = 0        # Number of moves played
        self.white_time: Optional[int] = None  # Final white time in seconds
        self.black_time: Optional[int] = None  # Final black time in seconds
        
        # Create TextWidgets for each line - use parent handler for child updates
        self._winner_text = TextWidget(0, 4, width, 18, self._handle_child_update,
                                        text="", font_size=16,
                                        justify=Justify.CENTER, transparent=True)
        self._termination_text = TextWidget(0, 24, width, 16, self._handle_child_update,
                                            text="", font_size=12,
                                            justify=Justify.CENTER, transparent=True)
        self._moves_text = TextWidget(0, 44, width, 14, self._handle_child_update,
                                      text="", font_size=10,
                                      justify=Justify.CENTER, transparent=True)
        self._times_text = TextWidget(0, 58, width, 14, self._handle_child_update,
                                      text="", font_size=10,
                                      justify=Justify.CENTER, transparent=True)
    
    def _handle_child_update(self, full: bool = False, immediate: bool = False):
        """Handle update requests from child widgets by forwarding to parent callback."""
        return self._update_callback(full, immediate)
    
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
            self.invalidate_cache()
            self.request_update(full=False)
    
    def show(self) -> None:
        """Show game over widget and turn off LEDs.
        
        When the game ends, any pending move or check/threat LEDs
        should be turned off to indicate the game is finished.
        """
        try:
            from DGTCentaurMods.board import board
            board.ledsOff()
            log.debug("[GameOverWidget] LEDs turned off on game over")
        except Exception as e:
            log.error(f"[GameOverWidget] Error turning off LEDs: {e}")
        
        super().show()
    
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
    
    def render(self, sprite: Image.Image) -> None:
        """
        Render game over widget using TextWidgets.
        
        Layout (72 pixels height):
        - Line 1 (y=4): Winner (e.g., "White wins", "Black wins", "Draw")
        - Line 2 (y=24): Termination reason (e.g., "Checkmate", "Resignation")
        - Line 3 (y=44): Move count (e.g., "42 moves")
        - Line 4 (y=58): Final times if available (e.g., "W:5:23 B:3:17")
        """
        draw = ImageDraw.Draw(sprite)
        
        # Draw background
        self.draw_background_on_sprite(sprite)
        
        # Draw separator line at top
        draw.line([(0, 0), (self.width, 0)], fill=0, width=1)
        
        # Line 1: Winner (centered, large font)
        if self.winner:
            self._winner_text.set_text(self.winner)
            self._winner_text.draw_on(sprite, 0, 4)
        
        # Line 2: Termination reason (centered, medium font)
        if self.termination:
            self._termination_text.set_text(self.termination)
            self._termination_text.draw_on(sprite, 0, 24)
        
        # Line 3: Move count (centered, small font)
        if self.move_count > 0:
            self._moves_text.set_text(f"{self.move_count} moves")
            self._moves_text.draw_on(sprite, 0, 44)
        
        # Line 4: Final times if available (centered, small font)
        if self.white_time is not None and self.black_time is not None:
            white_str = self._format_time(self.white_time)
            black_str = self._format_time(self.black_time)
            self._times_text.set_text(f"W:{white_str}  B:{black_str}")
            self._times_text.draw_on(sprite, 0, 58)
