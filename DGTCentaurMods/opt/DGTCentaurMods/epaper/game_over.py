"""
Game over screen widget displaying game result and score history.
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


class GameOverWidget(Widget):
    """Widget displaying game over screen with result and score history."""
    
    def __init__(self, x: int = 0, y: int = 0, width: int = 128, height: int = 296):
        """
        Initialize game over widget.
        
        Args:
            x: X position
            y: Y position
            width: Widget width
            height: Widget height
        """
        super().__init__(x, y, width, height)
        self.result_text = ""
        self.score_history = []
        self._font_18 = self._load_font()
    
    def _load_font(self):
        """Load font with Font.ttc as default."""
        if AssetManager is not None:
            try:
                font_path = AssetManager.get_resource_path("Font.ttc")
                if font_path and os.path.exists(font_path):
                    return ImageFont.truetype(font_path, 18)
            except:
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
                    return ImageFont.truetype(path, 18)
                except:
                    pass
        return ImageFont.load_default()
    
    def set_result(self, result: str) -> None:
        """Set the game result text."""
        if self.result_text != result:
            self.result_text = result
            self._last_rendered = None
            self.request_update(full=False)
    
    def set_score_history(self, history: list) -> None:
        """Set the score history for the graph."""
        if self.score_history != history:
            self.score_history = history.copy() if history else []
            self._last_rendered = None
            self.request_update(full=False)
    
    def render(self) -> Image.Image:
        """Render game over screen with result and score history."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Draw "GAME OVER" text
        draw.text((0, 0), "   GAME OVER", font=self._font_18, fill=0)
        
        # Draw result text
        if self.result_text:
            draw.text((0, 20), "          " + self.result_text, font=self._font_18, fill=0)
        
        # Draw score history graph if available
        if len(self.score_history) > 0:
            # Draw horizontal line at y=114
            draw.line([(0, 114), (self.width, 114)], fill=0, width=1)
            
            # Calculate bar width
            bar_width = self.width / len(self.score_history)
            if bar_width > 8:
                bar_width = 8
            
            # Draw bars
            bar_offset = 0
            for score in self.score_history:
                color = 255 if score >= 0 else 0
                bar_height = abs(score * 4)
                y1 = 114 - bar_height if score >= 0 else 114
                y2 = 114 if score >= 0 else 114 + bar_height
                draw.rectangle(
                    [(bar_offset, y1), (bar_offset + bar_width, y2)],
                    fill=color,
                    outline=0
                )
                bar_offset += bar_width
        
        return img

