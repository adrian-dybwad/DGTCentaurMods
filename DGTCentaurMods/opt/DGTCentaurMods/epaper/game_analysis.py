"""
Game analysis widget displaying evaluation score, history, and turn indicator.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
import os


class GameAnalysisWidget(Widget):
    """Widget displaying chess game analysis information."""
    
    def __init__(self, x: int, y: int, width: int = 128, height: int = 80, bottom_color: str = "black", analysis_engine=None):
        super().__init__(x, y, width, height)
        self.score_value = 0.0
        self.score_text = "0.0"
        self.score_history = []
        self.current_turn = "white"  # "white" or "black"
        self.bottom_color = bottom_color  # "white" or "black" - color at bottom of board
        self._font = self._load_font()
        self._max_history_size = 200
        self.analysis_engine = analysis_engine  # chess.engine.SimpleEngine for analysis
    
    def _load_font(self):
        """Load font with fallbacks."""
        font_paths = [
            '/opt/DGTCentaurMods/resources/Font.ttc',
            'resources/Font.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, 12)
                except:
                    pass
        return ImageFont.load_default()
    
    def set_score(self, score_value: float, score_text: str = None) -> None:
        """Set evaluation score."""
        old_score_text = self.score_text
        self.score_value = score_value
        if score_text is None:
            if abs(score_value) > 999:
                self.score_text = ""
            elif abs(score_value) >= 100:
                # Mate in X
                mate_moves = abs(score_value)
                self.score_text = f"Mate {int(mate_moves)}"
            else:
                self.score_text = f"{score_value:5.1f}"
        else:
            self.score_text = score_text
        # Only invalidate cache if score text actually changed
        if self.score_text != old_score_text:
            self._last_rendered = None
            # Trigger update if scheduler is available
            self.request_update(full=False)
    
    def add_score_to_history(self, score: float) -> None:
        """Add score to history."""
        # History always changes when adding, so always invalidate cache
        # The bar chart width depends on history length
        self.score_history.append(score)
        if len(self.score_history) > self._max_history_size:
            self.score_history.pop(0)
        self._last_rendered = None
        # Trigger update if scheduler is available
        self.request_update(full=False)
    
    def set_turn(self, turn: str) -> None:
        """Set current turn ('white' or 'black')."""
        if self.current_turn != turn:
            self.current_turn = turn
            self._last_rendered = None
            # Trigger update if scheduler is available
            self.request_update(full=False)
    
    def clear_history(self) -> None:
        """Clear score history."""
        self.score_history = []
        self._last_rendered = None
        # Trigger update if scheduler is available
        self.request_update(full=False)
    
    def get_score_history(self) -> list:
        """Get a copy of the score history."""
        return self.score_history.copy()
    
    def analyze_position(self, board, current_turn: str, is_first_move: bool = False, time_limit: float = 0.5) -> None:
        """
        Analyze a chess position using the analysis engine and update the widget.
        
        Sequence:
        1. Update all quick changes (turn indicator) - invalidate cache and trigger update
        2. Perform slow engine analysis
        3. Update score and history - invalidate cache and trigger update
        
        Args:
            board: chess.Board object to analyze
            current_turn: Current turn as "white" or "black"
            is_first_move: Whether this is the first move (skip adding to history)
            time_limit: Time limit for analysis in seconds (default 0.5)
        """
        if self.analysis_engine is None or board is None:
            return
        
        # Step 1: Update turn indicator immediately (fast operation)
        # This allows the turn circle to update before the slow analysis completes
        self.set_turn(current_turn)
        
        # Step 2: Perform slow engine analysis
        try:
            import chess.engine
            info = self.analysis_engine.analyse(board, chess.engine.Limit(time=time_limit))
            
            # Step 3: Update score and history (will invalidate cache and trigger update)
            self.update_from_analysis(info, current_turn, is_first_move)
        except Exception as e:
            # Log error but don't crash - widget will just not update score
            import logging
            log = logging.getLogger(__name__)
            log.warning(f"Error analyzing position: {e}")
    
    def update_from_analysis(self, analysis_info: dict, current_turn: str, is_first_move: bool = False) -> None:
        """
        Update widget from raw chess engine analysis info.
        
        Handles all parsing, formatting, and history management internally.
        Updates all state, then invalidates cache and triggers a single update.
        
        Args:
            analysis_info: Raw analysis info dict from chess engine (must contain "score")
            current_turn: Current turn as "white" or "black" (already updated in analyze_position)
            is_first_move: Whether this is the first move (skip adding to history)
        """
        if "score" not in analysis_info:
            return
        
        # Extract score value from engine analysis info
        score_str = str(analysis_info["score"])
        
        if "Mate" in score_str:
            # Extract mate value
            mate_str = score_str[13:24]
            mate_str = mate_str[1:mate_str.find(")")]
            score_value = float(mate_str)
            score_value = score_value / 100
        else:
            # Extract centipawn value
            cp_str = score_str[11:24]
            cp_str = cp_str[1:cp_str.find(")")]
            score_value = float(cp_str)
            score_value = score_value / 100
        
        # Negate if black is winning (scores are from white's perspective)
        if "BLACK" in score_str:
            score_value = score_value * -1
        
        # Format score text
        score_text = "{:5.1f}".format(score_value)
        if score_value > 999:
            score_text = ""
        
        # Handle mate scores
        if "Mate" in score_str:
            mate_moves = abs(score_value * 100)
            score_text = "Mate in " + "{:2.0f}".format(mate_moves)
            score_value = score_value * 100000
        
        # Clamp score for display (between -12 and 12)
        display_score = score_value
        if display_score > 12:
            display_score = 12
        if display_score < -12:
            display_score = -12
        
        # Update score state directly (without triggering update)
        self.score_value = display_score
        self.score_text = score_text
        
        # Add to history (skip first move)
        if not is_first_move:
            self.score_history.append(display_score)
            if len(self.score_history) > self._max_history_size:
                self.score_history.pop(0)
        
        # Single cache invalidation and update trigger for all changes
        self._last_rendered = None
        self.request_update(full=False)
    
    def render(self) -> Image.Image:
        """Render analysis widget."""
        # Return cached image if available
        if self._last_rendered is not None:
            return self._last_rendered
        
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Adjust score for display based on bottom color
        # Score is always from white's perspective (positive = white advantage)
        # If bottom is black (board is flipped), we need to flip (negative = black losing, positive = black winning)
        # If bottom is white (board not flipped), no adjustment needed (positive = white winning, negative = white losing)
        # This ensures negative always represents bottom color's disadvantage
        display_score_value = -self.score_value if self.bottom_color == "black" else self.score_value
        
        # Format score text for display (adjust if needed)
        # Regenerate text from adjusted display_score_value to ensure consistency
        if self.bottom_color == "black":
            # Regenerate text from adjusted score to match the bar display
            if abs(display_score_value) > 999:
                display_score_text = ""
            elif abs(display_score_value) >= 100:
                mate_moves = abs(display_score_value)
                display_score_text = f"Mate {int(mate_moves)}"
            else:
                display_score_text = f"{display_score_value:5.1f}"
        else:
            # Use original text (no adjustment needed when bottom is white - board not flipped)
            display_score_text = self.score_text
        
        # Draw score text
        if display_score_text:
            draw.text((50, 12), display_score_text, font=self._font, fill=0)
        
        # Draw score indicator box
        draw.rectangle([(0, 1), (127, 11)], fill=None, outline=0)
        
        # Calculate indicator position (clamp score between -12 and 12)
        score_display = display_score_value
        if score_display > 12:
            score_display = 12
        if score_display < -12:
            score_display = -12
        
        # Draw indicator bar
        offset = (128 / 25) * (score_display + 12)
        if offset < 128:
            draw.rectangle([(int(offset), 1), (127, 11)], fill=0, outline=0)
        
        # Draw score history bar chart
        if len(self.score_history) > 0:
            chart_y = 50
            draw.line([(0, chart_y), (128, chart_y)], fill=0, width=1)
            
            bar_width = 128 / len(self.score_history)
            if bar_width > 8:
                bar_width = 8
            
            bar_offset = 0
            for score in self.score_history:
                # Adjust score for display if bottom_color is black (board is flipped)
                adjusted_score = -score if self.bottom_color == "black" else score
                color = 255 if adjusted_score >= 0 else 0
                y_calc = chart_y - (adjusted_score * 2)
                y0 = min(chart_y, y_calc)
                y1 = max(chart_y, y_calc)
                draw.rectangle(
                    [(int(bar_offset), int(y0)), (int(bar_offset + bar_width), int(y1))],
                    fill=color,
                    outline=0
                )
                bar_offset += bar_width
        
        # Draw turn indicator showing which color is at the bottom of the board
        # When board is flipped (bottom_color == "black"), we need to invert the turn
        # to show which color is physically at the bottom
        if self.bottom_color == "black":
            # Board is flipped: invert the turn to show bottom color
            bottom_turn = "black" if self.current_turn == "white" else "white"
        else:
            # Board not flipped: turn directly indicates bottom color
            bottom_turn = self.current_turn
        
        # Draw circle: white circle (fill=255) for white at bottom, black circle (fill=0) for black at bottom
        if bottom_turn == "white":
            draw.ellipse((119, 14, 126, 21), fill=255, outline=0)
        else:
            draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
        
        # Cache the rendered image
        self._last_rendered = img
        return img

