"""
Icon button widget for e-paper display.

A single button with an icon and label, designed for large touch-friendly
button menus on the small e-paper display.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
from typing import Optional
import math

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

try:
    from DGTCentaurMods.asset_manager import AssetManager
except ImportError:
    AssetManager = None


# Default layout constants
DEFAULT_ICON_SIZE = 36
DEFAULT_LABEL_HEIGHT = 18
DEFAULT_PADDING = 6


class IconButtonWidget(Widget):
    """Widget displaying a single button with icon and label.
    
    The button can be in selected (inverted colors) or unselected state.
    Icons are drawn using PIL primitives for e-paper compatibility.
    
    Attributes:
        key: Unique identifier for this button
        label: Display text
        icon_name: Icon identifier for rendering
        selected: Whether button is currently selected (inverted)
    """
    
    def __init__(self, x: int, y: int, width: int, height: int,
                 key: str, label: str, icon_name: str,
                 selected: bool = False,
                 icon_size: int = DEFAULT_ICON_SIZE,
                 label_height: int = DEFAULT_LABEL_HEIGHT,
                 padding: int = DEFAULT_PADDING):
        """Initialize icon button widget.
        
        Args:
            x: X position of widget
            y: Y position of widget
            width: Widget width
            height: Widget height
            key: Unique identifier returned on selection
            label: Display text
            icon_name: Icon identifier for rendering
            selected: Initial selection state
            icon_size: Icon size in pixels
            label_height: Height reserved for label text
            padding: Internal padding
        """
        super().__init__(x, y, width, height)
        self.key = key
        self.label = label
        self.icon_name = icon_name
        self.selected = selected
        self.icon_size = icon_size
        self.label_height = label_height
        self.padding = padding
        
        # Load font
        self._font = None
        self._load_font()
    
    def _load_font(self):
        """Load font for label rendering."""
        try:
            if AssetManager:
                self._font = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 16)
            else:
                self._font = ImageFont.load_default()
        except Exception as e:
            log.error(f"Failed to load font: {e}")
            self._font = ImageFont.load_default()
    
    def set_selected(self, selected: bool) -> None:
        """Set the selection state.
        
        Args:
            selected: New selection state
        """
        if selected != self.selected:
            self.selected = selected
            self._last_rendered = None
            self.request_update(full=False)
    
    def render(self) -> Image.Image:
        """Render the button with icon and label.
        
        Returns:
            PIL Image with rendered button
        """
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Draw button background
        if self.selected:
            # Selected: filled black rectangle
            draw.rectangle([0, 0, self.width - 1, self.height - 1], fill=0, outline=0)
        else:
            # Unselected: white with black border
            draw.rectangle([0, 0, self.width - 1, self.height - 1], fill=255, outline=0, width=2)
        
        # Draw icon
        icon_x = self.padding + self.icon_size // 2
        icon_y = (self.height - self.label_height) // 2
        self._draw_icon(draw, self.icon_name, icon_x, icon_y, self.icon_size, self.selected)
        
        # Draw label
        text_x = icon_x + self.icon_size // 2 + self.padding
        text_y = self.height - self.label_height - 4
        text_color = 255 if self.selected else 0
        draw.text((text_x, text_y), self.label, font=self._font, fill=text_color)
        
        return img
    
    def _draw_icon(self, draw: ImageDraw.Draw, icon_name: str,
                   x: int, y: int, size: int, selected: bool):
        """Draw an icon at the specified position.
        
        Icons are drawn using PIL drawing primitives for e-paper
        compatibility and file independence.
        
        Args:
            draw: ImageDraw object
            icon_name: Icon identifier
            x: X position (center of icon)
            y: Y position (center of icon)
            size: Icon size in pixels
            selected: Whether this icon is in a selected button
        """
        half = size // 2
        left = x - half
        top = y - half
        right = x + half
        bottom = y + half
        
        # Line color (white for selected/inverted, black for normal)
        line_color = 255 if selected else 0
        
        if icon_name == "centaur":
            self._draw_knight_icon(draw, x, y, size, line_color, selected)
        elif icon_name == "universal":
            self._draw_universal_icon(draw, x, y, size, line_color, selected)
        elif icon_name == "settings":
            self._draw_gear_icon(draw, x, y, size, line_color)
        elif icon_name == "resign":
            self._draw_resign_icon(draw, x, y, size, line_color)
        elif icon_name == "draw":
            self._draw_draw_icon(draw, x, y, size, line_color)
        elif icon_name == "cancel":
            self._draw_cancel_icon(draw, x, y, size, line_color)
        elif icon_name == "exit":
            self._draw_exit_icon(draw, x, y, size, line_color)
        elif icon_name == "sound":
            self._draw_sound_icon(draw, x, y, size, line_color)
        elif icon_name == "shutdown":
            self._draw_power_icon(draw, x, y, size, line_color)
        elif icon_name == "reboot":
            self._draw_reboot_icon(draw, x, y, size, line_color)
        elif icon_name in ("Qw", "Qb"):
            self._draw_queen_icon(draw, x, y, size, line_color, selected, icon_name == "Qw")
        elif icon_name in ("Rw", "Rb"):
            self._draw_rook_icon(draw, x, y, size, line_color, selected, icon_name == "Rw")
        elif icon_name in ("Bw", "Bb"):
            self._draw_bishop_icon(draw, x, y, size, line_color, selected, icon_name == "Bw")
        elif icon_name in ("Nw", "Nb"):
            self._draw_knight_piece_icon(draw, x, y, size, line_color, selected, icon_name == "Nw")
        else:
            # Default: simple square placeholder
            draw.rectangle([left + 4, top + 4, right - 4, bottom - 4],
                          outline=line_color, width=2)
    
    def _draw_knight_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                          size: int, line_color: int, selected: bool):
        """Draw a chess knight icon."""
        half = size // 2
        left = x - half
        top = y - half
        right = x + half
        bottom = y + half
        s = size / 36.0  # Scale factor
        
        # Knight head and neck profile
        knight_points = [
            (left + int(4*s), bottom - int(2*s)),
            (right - int(4*s), bottom - int(2*s)),
            (right - int(6*s), bottom - int(8*s)),
            (right - int(4*s), bottom - int(14*s)),
            (right - int(6*s), top + int(10*s)),
            (right - int(8*s), top + int(6*s)),
            (right - int(10*s), top + int(4*s)),
            (x, top + int(2*s)),
            (left + int(10*s), top + int(4*s)),
            (left + int(6*s), top + int(8*s)),
            (left + int(4*s), top + int(12*s)),
            (left + int(6*s), top + int(14*s)),
            (left + int(8*s), y + int(2*s)),
            (left + int(6*s), bottom - int(10*s)),
            (left + int(4*s), bottom - int(6*s)),
        ]
        draw.polygon(knight_points, outline=line_color, fill=line_color)
        
        # Eye (hollow circle for contrast)
        eye_x = x + int(2*s)
        eye_y = top + int(10*s)
        eye_r = int(2*s)
        eye_color = 0 if selected else 255
        draw.ellipse([eye_x - eye_r, eye_y - eye_r, eye_x + eye_r, eye_y + eye_r],
                    fill=eye_color, outline=eye_color)
    
    def _draw_universal_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                             size: int, line_color: int, selected: bool):
        """Draw chess pieces with Bluetooth symbol."""
        half = size // 2
        left = x - half
        right = x + half
        bottom = y + half
        s = size / 36.0
        
        # Left side: Small pawn silhouette
        pawn_x = left + int(6*s)
        pawn_bottom = bottom - int(4*s)
        draw.rectangle([pawn_x - int(4*s), pawn_bottom - int(3*s),
                       pawn_x + int(4*s), pawn_bottom], fill=line_color)
        draw.polygon([
            (pawn_x - int(3*s), pawn_bottom - int(3*s)),
            (pawn_x - int(2*s), pawn_bottom - int(10*s)),
            (pawn_x + int(2*s), pawn_bottom - int(10*s)),
            (pawn_x + int(3*s), pawn_bottom - int(3*s)),
        ], fill=line_color)
        draw.ellipse([pawn_x - int(3*s), pawn_bottom - int(16*s),
                     pawn_x + int(3*s), pawn_bottom - int(10*s)], fill=line_color)
        
        # Right side: Small rook silhouette
        rook_x = right - int(6*s)
        rook_bottom = bottom - int(4*s)
        draw.rectangle([rook_x - int(4*s), rook_bottom - int(3*s),
                       rook_x + int(4*s), rook_bottom], fill=line_color)
        draw.rectangle([rook_x - int(3*s), rook_bottom - int(12*s),
                       rook_x + int(3*s), rook_bottom - int(3*s)], fill=line_color)
        draw.rectangle([rook_x - int(4*s), rook_bottom - int(16*s),
                       rook_x + int(4*s), rook_bottom - int(12*s)], fill=line_color)
        gap_color = 0 if selected else 255
        draw.rectangle([rook_x - int(1*s), rook_bottom - int(16*s),
                       rook_x + int(1*s), rook_bottom - int(13*s)], fill=gap_color)
        
        # Center: Bluetooth symbol
        bt_x = x
        bt_y = y - int(2*s)
        bt_h = int(14*s)
        bt_w = int(8*s)
        
        draw.line([(bt_x, bt_y - bt_h//2), (bt_x, bt_y + bt_h//2)],
                 fill=line_color, width=max(1, int(1.5*s)))
        draw.line([(bt_x, bt_y - bt_h//2), (bt_x + bt_w//2, bt_y - bt_h//4)],
                 fill=line_color, width=max(1, int(1.5*s)))
        draw.line([(bt_x + bt_w//2, bt_y - bt_h//4), (bt_x, bt_y)],
                 fill=line_color, width=max(1, int(1.5*s)))
        draw.line([(bt_x, bt_y + bt_h//2), (bt_x + bt_w//2, bt_y + bt_h//4)],
                 fill=line_color, width=max(1, int(1.5*s)))
        draw.line([(bt_x + bt_w//2, bt_y + bt_h//4), (bt_x, bt_y)],
                 fill=line_color, width=max(1, int(1.5*s)))
    
    def _draw_gear_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                        size: int, line_color: int):
        """Draw a gear/cog icon."""
        half = size // 2
        outer_r = half - 2
        inner_r = half // 2
        
        draw.ellipse([x - outer_r, y - outer_r, x + outer_r, y + outer_r],
                    outline=line_color, width=2)
        draw.ellipse([x - inner_r, y - inner_r, x + inner_r, y + inner_r],
                    outline=line_color, width=2)
        
        # Gear teeth
        tooth_len = 6
        for i in range(8):
            angle = i * (360 / 8) * (math.pi / 180)
            ix = x + int(outer_r * math.cos(angle))
            iy = y + int(outer_r * math.sin(angle))
            ox = x + int((outer_r + tooth_len) * math.cos(angle))
            oy = y + int((outer_r + tooth_len) * math.sin(angle))
            draw.line([(ix, iy), (ox, oy)], fill=line_color, width=2)
    
    def _draw_resign_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                          size: int, line_color: int):
        """Draw a flag (resign) icon."""
        half = size // 2
        left = x - half
        top = y - half
        bottom = y + half
        
        # Flag pole
        pole_x = left + 4
        draw.line([(pole_x, top + 2), (pole_x, bottom - 2)], fill=line_color, width=2)
        
        # Flag (wavy)
        flag_top = top + 4
        flag_bottom = y
        flag_right = x + half - 4
        draw.polygon([
            (pole_x, flag_top),
            (flag_right, flag_top + 4),
            (flag_right - 4, (flag_top + flag_bottom) // 2),
            (flag_right, flag_bottom - 4),
            (pole_x, flag_bottom),
        ], fill=line_color, outline=line_color)
    
    def _draw_draw_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                        size: int, line_color: int):
        """Draw a handshake (draw offer) icon - simplified as two hands."""
        half = size // 2
        
        # Two overlapping circles representing agreement
        r = half // 2
        draw.ellipse([x - r - 4, y - r, x + r - 4, y + r], outline=line_color, width=2)
        draw.ellipse([x - r + 4, y - r, x + r + 4, y + r], outline=line_color, width=2)
        
        # Equals sign below
        draw.line([(x - half + 6, y + half - 8), (x + half - 6, y + half - 8)],
                 fill=line_color, width=2)
        draw.line([(x - half + 6, y + half - 3), (x + half - 6, y + half - 3)],
                 fill=line_color, width=2)
    
    def _draw_cancel_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                          size: int, line_color: int):
        """Draw an X (cancel) icon."""
        half = size // 2
        margin = 6
        
        # X shape
        draw.line([(x - half + margin, y - half + margin),
                  (x + half - margin, y + half - margin)], fill=line_color, width=3)
        draw.line([(x + half - margin, y - half + margin),
                  (x - half + margin, y + half - margin)], fill=line_color, width=3)
    
    def _draw_exit_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                        size: int, line_color: int):
        """Draw a door with arrow (exit) icon."""
        half = size // 2
        left = x - half
        top = y - half
        right = x + half
        bottom = y + half
        
        # Door frame
        draw.rectangle([left + 4, top + 2, right - 8, bottom - 2], outline=line_color, width=2)
        
        # Arrow pointing right/out
        arrow_y = y
        arrow_start = x
        arrow_end = right - 2
        draw.line([(arrow_start, arrow_y), (arrow_end, arrow_y)], fill=line_color, width=2)
        draw.line([(arrow_end - 6, arrow_y - 6), (arrow_end, arrow_y)], fill=line_color, width=2)
        draw.line([(arrow_end - 6, arrow_y + 6), (arrow_end, arrow_y)], fill=line_color, width=2)
    
    def _draw_sound_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                         size: int, line_color: int):
        """Draw a speaker icon."""
        half = size // 2
        
        # Speaker body
        draw.polygon([
            (x - half + 4, y - 4),
            (x - half + 4, y + 4),
            (x - half + 10, y + 4),
            (x - half + 16, y + half - 4),
            (x - half + 16, y - half + 4),
            (x - half + 10, y - 4),
        ], fill=line_color)
        
        # Sound waves
        for i, offset in enumerate([6, 12]):
            arc_x = x - half + 16 + offset
            draw.arc([arc_x - 4, y - 8 - i*2, arc_x + 4, y + 8 + i*2],
                    start=-60, end=60, fill=line_color, width=2)
    
    def _draw_power_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                         size: int, line_color: int):
        """Draw a power button icon."""
        half = size // 2
        r = half - 4
        
        # Circle with gap at top
        draw.arc([x - r, y - r, x + r, y + r], start=50, end=310, fill=line_color, width=2)
        
        # Vertical line at top
        draw.line([(x, y - r - 2), (x, y - 2)], fill=line_color, width=2)
    
    def _draw_reboot_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                          size: int, line_color: int):
        """Draw a circular arrow (reboot) icon."""
        half = size // 2
        r = half - 4
        
        # Circular arc
        draw.arc([x - r, y - r, x + r, y + r], start=30, end=330, fill=line_color, width=2)
        
        # Arrow head at end of arc
        arrow_x = x + int(r * math.cos(math.radians(30)))
        arrow_y = y - int(r * math.sin(math.radians(30)))
        draw.polygon([
            (arrow_x, arrow_y),
            (arrow_x + 6, arrow_y + 2),
            (arrow_x + 2, arrow_y + 6),
        ], fill=line_color)
    
    def _draw_queen_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                         size: int, line_color: int, selected: bool, is_white: bool):
        """Draw a queen chess piece icon.
        
        Args:
            draw: ImageDraw object
            x: X center position
            y: Y center position
            size: Icon size in pixels
            line_color: Line color (0=black, 255=white)
            selected: Whether button is selected
            is_white: Whether to draw white piece (filled) or black piece (outline)
        """
        half = size // 2
        s = size / 36.0  # Scale factor
        
        # Base
        base_top = y + half - int(6*s)
        draw.rectangle([x - int(10*s), base_top, x + int(10*s), y + half - int(2*s)],
                      fill=line_color, outline=line_color)
        
        # Body (trapezoid)
        body_points = [
            (x - int(8*s), base_top),
            (x - int(6*s), y - int(4*s)),
            (x + int(6*s), y - int(4*s)),
            (x + int(8*s), base_top),
        ]
        draw.polygon(body_points, fill=line_color, outline=line_color)
        
        # Crown points (5 spikes)
        crown_base = y - int(4*s)
        crown_top = y - half + int(2*s)
        for i in range(5):
            spike_x = x + int((i - 2) * 4 * s)
            draw.polygon([
                (spike_x - int(2*s), crown_base),
                (spike_x, crown_top),
                (spike_x + int(2*s), crown_base),
            ], fill=line_color, outline=line_color)
            # Small circle on top of each spike
            draw.ellipse([spike_x - int(2*s), crown_top - int(2*s),
                         spike_x + int(2*s), crown_top + int(2*s)],
                        fill=line_color, outline=line_color)
    
    def _draw_rook_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                        size: int, line_color: int, selected: bool, is_white: bool):
        """Draw a rook chess piece icon."""
        half = size // 2
        s = size / 36.0
        
        # Base
        base_top = y + half - int(6*s)
        draw.rectangle([x - int(10*s), base_top, x + int(10*s), y + half - int(2*s)],
                      fill=line_color, outline=line_color)
        
        # Body
        draw.rectangle([x - int(7*s), y - int(4*s), x + int(7*s), base_top],
                      fill=line_color, outline=line_color)
        
        # Battlements (top)
        battlement_base = y - int(4*s)
        battlement_top = y - half + int(2*s)
        draw.rectangle([x - int(9*s), battlement_base, x + int(9*s), battlement_top + int(4*s)],
                      fill=line_color, outline=line_color)
        
        # Cut out the gaps in battlements
        gap_color = 0 if selected else 255
        for i in [-1, 1]:
            gap_x = x + int(i * 4 * s)
            draw.rectangle([gap_x - int(2*s), battlement_top,
                           gap_x + int(2*s), battlement_top + int(4*s)],
                          fill=gap_color, outline=gap_color)
    
    def _draw_bishop_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                          size: int, line_color: int, selected: bool, is_white: bool):
        """Draw a bishop chess piece icon."""
        half = size // 2
        s = size / 36.0
        
        # Base
        base_top = y + half - int(6*s)
        draw.rectangle([x - int(8*s), base_top, x + int(8*s), y + half - int(2*s)],
                      fill=line_color, outline=line_color)
        
        # Body (tapered)
        body_points = [
            (x - int(6*s), base_top),
            (x - int(4*s), y),
            (x, y - int(8*s)),
            (x + int(4*s), y),
            (x + int(6*s), base_top),
        ]
        draw.polygon(body_points, fill=line_color, outline=line_color)
        
        # Mitre top (pointed hat)
        draw.polygon([
            (x - int(4*s), y - int(8*s)),
            (x, y - half + int(2*s)),
            (x + int(4*s), y - int(8*s)),
        ], fill=line_color, outline=line_color)
        
        # Small ball on top
        draw.ellipse([x - int(2*s), y - half, x + int(2*s), y - half + int(4*s)],
                    fill=line_color, outline=line_color)
        
        # Diagonal slit on mitre
        slit_color = 0 if selected else 255
        draw.line([(x - int(2*s), y - int(6*s)), (x + int(2*s), y - int(10*s))],
                 fill=slit_color, width=max(1, int(1.5*s)))
    
    def _draw_knight_piece_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                                size: int, line_color: int, selected: bool, is_white: bool):
        """Draw a knight chess piece icon (for promotion menu).
        
        Similar to _draw_knight_icon but designed for promotion context.
        """
        # Reuse the existing knight icon drawing
        self._draw_knight_icon(draw, x, y, size, line_color, selected)
