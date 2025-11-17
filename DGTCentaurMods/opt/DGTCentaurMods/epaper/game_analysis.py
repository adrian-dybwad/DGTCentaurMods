"""
Game analysis widget displaying evaluation score, history, and turn indicator.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
import os


class GameAnalysisWidget(Widget):
    """Widget displaying chess game analysis information."""
    
    def __init__(self, x: int, y: int, width: int = 128, height: int = 80):
        super().__init__(x, y, width, height)
        self.score_value = 0.0
        self.score_text = "0.0"
        self.score_history = []
        self.current_turn = "white"  # "white" or "black"
        self._font = self._load_font()
        self._max_history_size = 200
    
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
        self._last_rendered = None
    
    def add_score_to_history(self, score: float) -> None:
        """Add score to history."""
        self.score_history.append(score)
        if len(self.score_history) > self._max_history_size:
            self.score_history.pop(0)
        self._last_rendered = None
    
    def set_turn(self, turn: str) -> None:
        """Set current turn ('white' or 'black')."""
        self.current_turn = turn
        self._last_rendered = None
    
    def clear_history(self) -> None:
        """Clear score history."""
        self.score_history = []
        self._last_rendered = None
    
    def render(self) -> Image.Image:
        """Render analysis widget."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Draw score text
        if self.score_text:
            draw.text((50, 12), self.score_text, font=self._font, fill=0)
        
        # Draw score indicator box
        draw.rectangle([(0, 1), (127, 11)], fill=None, outline=0)
        
        # Calculate indicator position (clamp score between -12 and 12)
        score_display = self.score_value
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
                color = 255 if score >= 0 else 0
                y_calc = chart_y - (score * 2)
                y0 = min(chart_y, y_calc)
                y1 = max(chart_y, y_calc)
                draw.rectangle(
                    [(int(bar_offset), int(y0)), (int(bar_offset + bar_width), int(y1))],
                    fill=color,
                    outline=0
                )
                bar_offset += bar_width
        
        # Draw turn indicator (white circle for white, black circle for black)
        if self.current_turn == "white":
            draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
        else:
            draw.ellipse((119, 14, 126, 21), fill=255, outline=0)
        
        return img

