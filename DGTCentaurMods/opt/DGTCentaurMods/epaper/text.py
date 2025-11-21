"""
Text display widget.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
import os
import sys

try:
    from DGTCentaurMods.display.ui_components import AssetManager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from display.ui_components import AssetManager
    except ImportError:
        AssetManager = None


class TextWidget(Widget):
    """Text display widget with configurable background dithering."""
    
    def __init__(self, x: int, y: int, width: int, height: int, text: str = "", 
                 background: int = 0, font_size: int = 12, font_path: str = None):
        """
        Initialize text widget.
        
        Args:
            x: X position
            y: Y position
            width: Widget width
            height: Widget height
            text: Text to display
            background: Background dithering level (0-5)
                0 = no background (white)
                1 = very light dither (~17% black)
                2 = light dither (~33% black)
                3 = medium dither (~50% black, checkerboard)
                4 = heavy dither (~67% black)
                5 = solid black
            font_size: Font size in points
            font_path: Optional path to font file (defaults to Font.ttc if None)
        """
        super().__init__(x, y, width, height)
        self.text = text
        self.background = max(0, min(5, background))  # Clamp to 0-5
        self.font_size = font_size
        self.font_path = font_path
        self._font = self._load_font()
    
    def _load_font(self):
        """Load font with Font.ttc as default."""
        # If font_path is explicitly provided, use it
        if self.font_path and os.path.exists(self.font_path):
            try:
                return ImageFont.truetype(self.font_path, self.font_size)
            except:
                pass
        
        # Default to Font.ttc using AssetManager if available
        if AssetManager is not None:
            try:
                default_font_path = AssetManager.get_resource_path("Font.ttc")
                if default_font_path and os.path.exists(default_font_path):
                    try:
                        return ImageFont.truetype(default_font_path, self.font_size)
                    except:
                        pass
            except:
                pass
        
        # Fallback to direct paths
        font_paths = [
            '/opt/DGTCentaurMods/resources/Font.ttc',
            'resources/Font.ttc',
            '/opt/DGTCentaurMods/resources/fixed_01.ttf',
            'resources/fixed_01.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, self.font_size)
                except:
                    pass
        return ImageFont.load_default()
    
    def set_text(self, text: str) -> None:
        """Set the text to display."""
        if self.text != text:
            self.text = text
            self._last_rendered = None
            self.request_update(full=False)
    
    def set_background(self, background: int) -> None:
        """Set background dithering level (0-5)."""
        background = max(0, min(5, background))
        if self.background != background:
            self.background = background
            self._last_rendered = None
            self.request_update(full=False)
    
    def _create_dither_pattern(self) -> Image.Image:
        """Create dither pattern based on background level."""
        pattern = Image.new("1", (self.width, self.height), 255)
        
        if self.background == 0:
            # No background - all white
            return pattern
        elif self.background == 5:
            # Solid black
            draw = ImageDraw.Draw(pattern)
            draw.rectangle([0, 0, self.width, self.height], fill=0)
            return pattern
        
        # Dithering levels 1-4 using ordered dithering
        draw = ImageDraw.Draw(pattern)
        # Use a 4x4 Bayer dither matrix for better visual quality
        # Level 1: ~19% (3/16 black pixels)
        # Level 2: ~38% (6/16 black pixels)
        # Level 3: ~50% (8/16 black pixels) - checkerboard-like
        # Level 4: ~69% (11/16 black pixels)
        
        bayer_matrix = [
            [0, 8, 2, 10],
            [12, 4, 14, 6],
            [3, 11, 1, 9],
            [15, 7, 13, 5]
        ]
        
        # Thresholds for each level (out of 16)
        thresholds = {1: 3, 2: 6, 3: 8, 4: 11}
        threshold = thresholds.get(self.background, 8)
        
        for y in range(self.height):
            for x in range(self.width):
                pattern_x = x % 4
                pattern_y = y % 4
                value = bayer_matrix[pattern_y][pattern_x]
                if value < threshold:
                    draw.point((x, y), fill=0)
        
        return pattern
    
    def render(self) -> Image.Image:
        """Render text with background."""
        img = self._create_dither_pattern()
        draw = ImageDraw.Draw(img)
        
        # Determine text color based on background
        # For backgrounds 0-2, use black text; for 3-5, use white text
        text_fill = 0 if self.background < 3 else 255
        
        draw.text((0, -1), self.text, font=self._font, fill=text_fill)
        return img
