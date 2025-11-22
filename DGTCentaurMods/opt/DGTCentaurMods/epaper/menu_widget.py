"""
Menu widget that renders title, entries, arrow, and description.
"""

import os
from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
from typing import List, Optional, Sequence
from dataclasses import dataclass

try:
    from DGTCentaurMods.display.ui_components import AssetManager
except ImportError:
    AssetManager = None

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


@dataclass
class MenuEntry:
    key: str
    label: str
    description: Optional[str] = None


class MenuWidget(Widget):
    """Widget that renders a complete menu with title, entries, arrow, and description."""
    
    # Constants matching menu.py
    STATUS_BAR_HEIGHT = 16
    TITLE_GAP = 8
    TITLE_HEIGHT = 24
    MENU_ROW_HEIGHT = 20
    DESCRIPTION_GAP = 8
    ARROW_WIDTH = 20
    
    def __init__(self, x: int, y: int, width: int, height: int,
                 title: Optional[str] = None,
                 entries: Sequence[MenuEntry] = None,
                 selected_index: int = 0):
        """
        Initialize menu widget.
        
        Args:
            x: X position
            y: Y position
            width: Widget width (typically 128 for e-paper)
            height: Widget height (typically 296 for e-paper)
            title: Optional menu title
            entries: List of menu entries
            selected_index: Currently selected entry index
        """
        super().__init__(x, y, width, height)
        self.title = title or ""
        self.entries: List[MenuEntry] = list(entries) if entries else []
        self.selected_index = max(0, min(selected_index, len(self.entries) - 1) if self.entries else 0)
        
        # Calculate layout positions
        self._title_top = self.STATUS_BAR_HEIGHT + self.TITLE_GAP if self.title else 0
        self._menu_top = self._title_top + (self.TITLE_HEIGHT if self.title else 0)
        self._text_x = self.ARROW_WIDTH + 4  # Text starts after arrow column
        
        # Load fonts
        self._title_font = self._load_font(18)
        self._entry_font = self._load_font(16)
        self._description_font = self._load_font(14)
    
    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        """Load font with fallbacks."""
        font_paths = []
        if AssetManager is not None:
            try:
                default_font_path = AssetManager.get_resource_path("Font.ttc")
                if default_font_path:
                    font_paths.append(default_font_path)
            except:
                pass
        
        font_paths.extend([
            '/opt/DGTCentaurMods/resources/Font.ttc',
            'resources/Font.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ])
        
        for path in font_paths:
            try:
                if path and os.path.exists(path):
                    return ImageFont.truetype(path, size)
            except:
                continue
        
        return ImageFont.load_default()
    
    def set_selection(self, index: int) -> None:
        """Set the selected entry index and trigger re-render."""
        new_index = max(0, min(index, len(self.entries) - 1) if self.entries else 0)
        if new_index != self.selected_index:
            self.selected_index = new_index
            self._last_rendered = None  # Invalidate cache
            self.request_update(full=False)
    
    def set_entries(self, entries: Sequence[MenuEntry], selected_index: int = 0) -> None:
        """Update menu entries and trigger re-render."""
        self.entries = list(entries)
        self.set_selection(selected_index)
    
    def _row_top(self, idx: int) -> int:
        """Calculate Y position for a menu row."""
        return self._menu_top + (idx * self.MENU_ROW_HEIGHT)
    
    def _wrap_text(self, text: str, max_width: int, font: ImageFont.FreeTypeFont) -> List[str]:
        """Wrap text to fit within max_width using the specified font."""
        words = text.split()
        if not words:
            return []
        
        lines = []
        current = words[0]
        temp_image = Image.new("1", (1, 1), 255)
        temp_draw = ImageDraw.Draw(temp_image)
        
        for word in words[1:]:
            candidate = f"{current} {word}"
            if temp_draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        
        lines.append(current)
        return lines
    
    def render(self) -> Image.Image:
        """Render the complete menu: title, entries, arrow, and description."""
        img = Image.new("1", (self.width, self.height), 255)  # White background
        draw = ImageDraw.Draw(img)
        
        # Draw title if present
        if self.title:
            title_text = f"[ {self.title} ]"
            title_y = self._title_top
            draw.text((0, title_y), title_text, font=self._title_font, fill=0)
        
        # Draw menu entries and arrow
        text_width = self.width - self._text_x
        for idx, entry in enumerate(self.entries):
            row_y = self._row_top(idx)
            
            # Draw entry text
            draw.text((self._text_x, row_y), entry.label, font=self._entry_font, fill=0)
            
            # Draw arrow if this is the selected entry
            if idx == self.selected_index:
                arrow_width = self.ARROW_WIDTH - 1  # Leave 1 pixel for vertical line
                draw.polygon(
                    [
                        (2, row_y + 2),
                        (2, row_y + self.MENU_ROW_HEIGHT - 2),
                        (arrow_width - 3, row_y + (self.MENU_ROW_HEIGHT // 2)),
                    ],
                    fill=0,
                )
        
        # Draw vertical line on the right side of arrow column
        menu_height = len(self.entries) * self.MENU_ROW_HEIGHT if self.entries else 0
        if menu_height > 0:
            draw.line((self.ARROW_WIDTH - 1, self._menu_top, self.ARROW_WIDTH - 1, 
                       self._menu_top + menu_height - 1), fill=0, width=1)
        
        # Draw description for selected entry
        if self.entries and self.selected_index < len(self.entries):
            entry = self.entries[self.selected_index]
            if entry.description:
                desc_text = entry.description
                desc_top = self._row_top(len(self.entries)) + self.DESCRIPTION_GAP
                desc_width = self.width - 10  # 5px margin on each side
                
                # Wrap text to fit width
                wrapped_lines = self._wrap_text(desc_text, desc_width, self._description_font)
                
                # Draw wrapped text
                line_height = 16  # Approximate line height for font size 14
                for line_idx, line in enumerate(wrapped_lines):
                    y_pos = desc_top + (line_idx * line_height)
                    if y_pos + line_height > self.height:
                        break  # Don't draw beyond widget height
                    draw.text((5, y_pos), line, font=self._description_font, fill=0)
        
        return img

