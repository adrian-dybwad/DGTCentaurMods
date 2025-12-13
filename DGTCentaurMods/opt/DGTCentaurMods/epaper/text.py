"""
Text display widget.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget, DITHER_PATTERNS
from enum import Enum
import os
import sys

try:
    from DGTCentaurMods.asset_manager import AssetManager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from asset_manager import AssetManager
    except ImportError:
        AssetManager = None


class Justify(Enum):
    """Text justification options."""
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class TextWidget(Widget):
    """Text display widget with configurable background dithering, text wrapping, and justification."""
    
    def __init__(self, x: int, y: int, width: int, height: int, text: str = "", 
                 background: int = -1, font_size: int = 12, font_path: str = None,
                 wrapText: bool = False, justify: Justify = Justify.LEFT,
                 transparent: bool = True):
        """
        Initialize text widget.
        
        Args:
            x: X position
            y: Y position
            width: Widget width
            height: Widget height
            text: Text to display
            background: Background dithering level (-1 to 5)
                -1 = transparent (default, inherits parent background)
                0 = no background (white)
                1 = very light dither (~17% black)
                2 = light dither (~33% black)
                3 = medium dither (~50% black, checkerboard)
                4 = heavy dither (~67% black)
                5 = solid black
            font_size: Font size in points
            font_path: Optional path to font file (defaults to Font.ttc if None)
            wrapText: If True, wrap text to fit within widget width and height
            justify: Text justification (Justify.LEFT, Justify.CENTER, or Justify.RIGHT)
            transparent: If True (default), background is transparent and text appears
                        over parent widget's pixels. Overrides background=-1.
        """
        super().__init__(x, y, width, height)
        self.text = text
        self.transparent = transparent
        # If transparent is True, force background to -1
        if transparent:
            self.background = -1
        else:
            self.background = max(-1, min(5, background))
        self.font_size = font_size
        self.font_path = font_path
        self.wrapText = wrapText
        self.justify = justify
        self._font = self._load_font()
        self._mask = None  # Cached mask image
    
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
            self._mask = None  # Invalidate mask cache
            self.request_update(full=False)
    
    def set_wrap_text(self, wrapText: bool) -> None:
        """Enable or disable text wrapping."""
        if self.wrapText != wrapText:
            self.wrapText = wrapText
            self._last_rendered = None
            self._mask = None  # Invalidate mask cache
            self.request_update(full=False)
    
    def set_background(self, background: int) -> None:
        """Set background dithering level (-1 to 5).
        
        Args:
            background: -1 for transparent, 0-5 for dithered backgrounds
        """
        background = max(-1, min(5, background))
        if self.background != background:
            self.background = background
            self.transparent = (background == -1)
            self._last_rendered = None
            self._mask = None
            self.request_update(full=False)
    
    def set_transparent(self, transparent: bool) -> None:
        """Set whether the background is transparent.
        
        Args:
            transparent: If True, background is transparent (inherits parent)
        """
        if self.transparent != transparent:
            self.transparent = transparent
            if transparent:
                self.background = -1
            elif self.background == -1:
                self.background = 0  # Default to white if was transparent
            self._last_rendered = None
            self._mask = None
            self.request_update(full=False)
    
    def set_justify(self, justify: Justify) -> None:
        """Set text justification."""
        if self.justify != justify:
            self.justify = justify
            self._last_rendered = None
            self._mask = None  # Invalidate mask cache
            self.request_update(full=False)
    
    def _get_text_width(self, text: str, draw: ImageDraw.Draw) -> int:
        """Get the width of text in pixels.
        
        Args:
            text: Text to measure
            draw: ImageDraw object for measuring
            
        Returns:
            Width in pixels
        """
        try:
            bbox = draw.textbbox((0, 0), text, font=self._font)
            return bbox[2] - bbox[0]
        except AttributeError:
            # Fallback for older PIL versions
            return int(draw.textlength(text, font=self._font))
    
    def _get_x_position(self, text: str, draw: ImageDraw.Draw) -> int:
        """Calculate x position based on justification.
        
        Args:
            text: Text to position
            draw: ImageDraw object for measuring
            
        Returns:
            X position in pixels
        """
        if self.justify == Justify.LEFT:
            return 0
        
        text_width = self._get_text_width(text, draw)
        
        if self.justify == Justify.CENTER:
            return (self.width - text_width) // 2
        elif self.justify == Justify.RIGHT:
            return self.width - text_width
        
        return 0
    
    def _create_dither_pattern(self) -> Image.Image:
        """Create dither pattern based on background level.
        
        Uses an 8x8 Bayer matrix for ordered dithering.
        For transparent backgrounds (-1), returns a white image since
        the actual compositing is handled via get_mask().
        """
        img = Image.new("1", (self.width, self.height), 255)
        
        if self.background <= 0:
            # Transparent (-1) or white (0) - all white
            return img
        elif self.background == 5:
            # Solid black
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, self.width, self.height], fill=0)
            return img
        
        # Map background levels 1-4 to shade levels for Bayer patterns
        # Level 1: ~20% black (shade 3)
        # Level 2: ~38% black (shade 6)
        # Level 3: ~50% black (shade 8)
        # Level 4: ~69% black (shade 11)
        shade_map = {1: 3, 2: 6, 3: 8, 4: 11}
        shade = shade_map.get(self.background, 8)
        
        pattern = DITHER_PATTERNS.get(shade, DITHER_PATTERNS[0])
        pixels = img.load()
        
        for y in range(self.height):
            pattern_row = pattern[y % 8]
            for x in range(self.width):
                if pattern_row[x % 8] == 1:
                    pixels[x, y] = 0  # Black pixel
        
        return img
    
    def get_mask(self):
        """Get mask for transparent compositing.
        
        For transparent TextWidgets, returns a mask where text pixels are
        white (opaque) and background pixels are black (transparent).
        This allows the parent widget's background to show through.
        
        Returns:
            Image mask if transparent, None otherwise
        """
        if not self.transparent:
            return None
        
        # Create mask where text is white (opaque) and background is black (transparent)
        # We render the text to determine which pixels should be opaque
        if self._mask is None:
            self._mask = self._create_text_mask()
        return self._mask
    
    def _create_text_mask(self) -> Image.Image:
        """Create a mask image for transparent text compositing.
        
        Returns:
            1-bit image where white=opaque (text), black=transparent (background)
        """
        # Start with all black (transparent)
        mask = Image.new("1", (self.width, self.height), 0)
        draw = ImageDraw.Draw(mask)
        
        if self.wrapText:
            wrapped_lines = self._wrap_text(self.text, self.width)
            line_height = self.font_size + 2
            max_lines = max(1, self.height // line_height)
            for idx, line in enumerate(wrapped_lines[:max_lines]):
                y_pos = idx * line_height
                if y_pos + line_height > self.height:
                    break
                x_pos = self._get_x_position(line, draw)
                # Draw text in white (opaque) on mask
                draw.text((x_pos, y_pos - 1), line, font=self._font, fill=255)
        else:
            x_pos = self._get_x_position(self.text, draw)
            draw.text((x_pos, -1), self.text, font=self._font, fill=255)
        
        return mask
    
    def _wrap_text(self, text: str, max_width: int) -> list:
        """
        Wrap text to fit within max_width using the widget's font.
        
        Respects explicit newlines in the text - each newline starts a new line.
        Then wraps long lines to fit within max_width.
        
        Args:
            text: Text to wrap (may contain \\n for explicit line breaks)
            max_width: Maximum width in pixels
            
        Returns:
            List of wrapped text lines
        """
        if not text:
            return []
        
        temp_image = Image.new("1", (1, 1), 255)
        temp_draw = ImageDraw.Draw(temp_image)
        
        lines = []
        
        # First split by explicit newlines
        paragraphs = text.split('\n')
        
        for paragraph in paragraphs:
            # Handle empty paragraphs (consecutive newlines)
            if not paragraph.strip():
                lines.append("")
                continue
            
            # Wrap this paragraph
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if temp_draw.textlength(candidate, font=self._font) <= max_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            
            lines.append(current)
        
        return lines
    
    def render(self) -> Image.Image:
        """Render text with background and justification.
        
        For transparent backgrounds, the text is rendered as black on white.
        The actual transparency is handled by get_mask() during compositing.
        """
        img = self._create_dither_pattern()
        draw = ImageDraw.Draw(img)
        
        # Determine text color based on background
        # For transparent (-1) or backgrounds 0-2, use black text; for 3-5, use white text
        text_fill = 0 if self.background < 3 else 255
        
        if self.wrapText:
            # Wrap text to fit within widget width
            wrapped_lines = self._wrap_text(self.text, self.width)
            
            # Calculate line height based on font size
            # Use font size + 2 pixels for spacing
            line_height = self.font_size + 2
            
            # Draw each line, respecting widget height
            max_lines = max(1, self.height // line_height)
            for idx, line in enumerate(wrapped_lines[:max_lines]):
                y_pos = idx * line_height
                # Stop if line would exceed widget height
                if y_pos + line_height > self.height:
                    break
                x_pos = self._get_x_position(line, draw)
                draw.text((x_pos, y_pos - 1), line, font=self._font, fill=text_fill)
        else:
            # Single line text with justification
            x_pos = self._get_x_position(self.text, draw)
            draw.text((x_pos, -1), self.text, font=self._font, fill=text_fill)
        
        return img
