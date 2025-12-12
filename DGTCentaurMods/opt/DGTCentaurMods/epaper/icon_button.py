"""
Icon button widget for e-paper display.

A single button with an icon and label, designed for large touch-friendly
button menus on the small e-paper display.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget, DITHER_PATTERNS
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
                 icon_size: int = 36,
                 label_height: int = 18,
                 margin: int = 4,
                 padding: int = 2,
                 icon_margin: int = 2,
                 border_width: int = 2,
                 selected_shade: int = 12,
                 background_shade: int = 0):
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
            icon_size: Icon size in pixels (default 36)
            label_height: Height reserved for label text (default 18)
            margin: Space outside the button border (default 4)
            padding: Space inside the button border (default 2)
            icon_margin: Space around the icon on all sides (default 2)
            border_width: Width of the button border in pixels (default 2)
            selected_shade: Dithered shade for selected state 0-16 (default 12 = ~75% black)
            background_shade: Dithered background shade 0-16 (default 0 = white)
        """
        super().__init__(x, y, width, height, background_shade=background_shade)
        self.key = key
        self.label = label
        self.icon_name = icon_name
        self.selected = selected
        self.icon_size = icon_size
        self.label_height = label_height
        self.margin = margin
        self.padding = padding
        self.icon_margin = icon_margin
        self.border_width = border_width
        self.selected_shade = max(0, min(16, selected_shade))
        
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
    
    def _apply_dither_pattern(self, img: Image.Image, shade: int) -> None:
        """Apply a dither pattern to an image.
        
        Uses an 8x8 Bayer matrix for smoother gradients.
        
        Args:
            img: Image to modify in place
            shade: Shade level 0-16 (0=white, 16=black)
        """
        pattern = DITHER_PATTERNS.get(shade, DITHER_PATTERNS[0])
        pixels = img.load()
        for y in range(img.height):
            pattern_row = pattern[y % 8]
            for x in range(img.width):
                if pattern_row[x % 8] == 1:
                    pixels[x, y] = 0  # Black pixel
    
    def render(self) -> Image.Image:
        """Render the button with icon and label.
        
        Multi-line labels are supported. For multi-line text, the label is
        positioned at the top of the button (after the icon). For single-line
        text, it remains at the bottom.
        
        Layout:
            - margin: transparent space outside the border
            - border: 2px black line
            - padding: space inside the border (between border and content)
        
        Returns:
            PIL Image with rendered button
        """
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Calculate border rectangle (inset by margin)
        border_left = self.margin
        border_top = self.margin
        border_right = self.width - 1 - self.margin
        border_bottom = self.height - 1 - self.margin
        
        # Inside edge of border (where content can start)
        inside_left = self.margin + self.border_width
        inside_top = self.margin + self.border_width
        inside_right = self.width - self.margin - self.border_width
        inside_bottom = self.height - self.margin - self.border_width
        
        # Content area bounds (inside border and padding)
        content_left = inside_left + self.padding
        content_top = inside_top + self.padding
        content_right = inside_right - self.padding
        content_bottom = inside_bottom - self.padding
        content_height = content_bottom - content_top
        
        # Draw button background (only inside border area, not margin)
        if self.selected:
            # Selected: dark grey dithered background inside border only
            for y in range(border_top, border_bottom + 1):
                for x in range(border_left, border_right + 1):
                    pattern = DITHER_PATTERNS.get(self.selected_shade, DITHER_PATTERNS[0])
                    if pattern[y % 8][x % 8] == 1:
                        img.putpixel((x, y), 0)
            # Draw border outline
            draw.rectangle([border_left, border_top, border_right, border_bottom], fill=None, outline=0)
        else:
            # Unselected: white fill with black border
            draw.rectangle([border_left, border_top, border_right, border_bottom], fill=255, outline=0, width=self.border_width)
        
        # Draw icon (icon_margin is space around icon on all sides, ignores padding)
        # Icon positioned from inside of border + icon_margin
        icon_left = inside_left + self.icon_margin
        icon_top = inside_top + self.icon_margin
        icon_x = icon_left + self.icon_size // 2
        icon_y = icon_top + self.icon_size // 2
        self._draw_icon(draw, self.icon_name, icon_x, icon_y, self.icon_size, self.selected)
        
        # Icon right edge (including icon_margin on right side)
        icon_right = icon_left + self.icon_size + self.icon_margin
        
        # Draw label (uses padding for vertical positioning, starts after icon area)
        text_x = icon_right
        text_color = 255 if self.selected else 0
        
        # Check for multi-line text
        lines = self.label.split('\n')
        if len(lines) > 1:
            # Multi-line: position at top of content area (uses padding)
            text_y = content_top
            for line in lines:
                draw.text((text_x, text_y), line, font=self._font, fill=text_color)
                text_y += 16  # Line height
        else:
            # Single line: center vertically in content area (uses padding)
            text_y = content_top + (content_height - self.label_height) // 2
            draw.text((text_x, text_y), self.label, font=self._font, fill=text_color)
        
        return img
    
    def get_mask(self):
        """Get mask for transparent margin.
        
        Returns a mask where the margin area is transparent (black in mask)
        and the button area is opaque (white in mask).
        """
        mask = Image.new("1", (self.width, self.height), 0)  # Start all transparent
        draw = ImageDraw.Draw(mask)
        
        # Make the button area (inside margin) opaque
        border_left = self.margin
        border_top = self.margin
        border_right = self.width - 1 - self.margin
        border_bottom = self.height - 1 - self.margin
        draw.rectangle([border_left, border_top, border_right, border_bottom], fill=255)
        
        return mask
    
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
        elif icon_name == "engine":
            self._draw_engine_icon(draw, x, y, size, line_color)
        elif icon_name == "elo":
            self._draw_elo_icon(draw, x, y, size, line_color)
        elif icon_name == "color":
            self._draw_color_icon(draw, x, y, size, line_color)
        elif icon_name == "white_piece":
            self._draw_king_icon(draw, x, y, size, line_color, is_white=True)
        elif icon_name == "black_piece":
            self._draw_king_icon(draw, x, y, size, line_color, is_white=False)
        elif icon_name == "random":
            self._draw_random_icon(draw, x, y, size, line_color)
        elif icon_name == "wifi":
            self._draw_wifi_icon(draw, x, y, size, line_color)
        elif icon_name == "wifi_strong":
            self._draw_wifi_signal_icon(draw, x, y, size, line_color, strength=3)
        elif icon_name == "wifi_medium":
            self._draw_wifi_signal_icon(draw, x, y, size, line_color, strength=2)
        elif icon_name == "wifi_weak":
            self._draw_wifi_signal_icon(draw, x, y, size, line_color, strength=1)
        elif icon_name == "system":
            self._draw_system_icon(draw, x, y, size, line_color)
        else:
            # Default: simple square placeholder
            draw.rectangle([left + 4, top + 4, right - 4, bottom - 4],
                          outline=line_color, width=2)
    
    def _draw_knight_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                          size: int, line_color: int, selected: bool):
        """Draw a chess knight icon.
        
        Uses path coordinates derived from python-chess (GPL-3.0+) SVG assets.
        The original SVG viewBox is 45x45, scaled to fit the icon size.
        Points are sampled from the bezier curves in the original SVG paths.
        """
        half = size // 2
        s = size / 45.0  # Scale factor (python-chess uses 45x45 viewBox)
        
        # Offset to center the 45x45 coordinate system in our icon area
        ox = x - half
        oy = y - half
        
        def pt(px: float, py: float) -> tuple:
            """Convert python-chess SVG coordinate to icon coordinate."""
            return (ox + int(px * s), oy + int(py * s))
        
        # Body polygon - sampled from bezier curve:
        # M 22,10 C 32.5,11 38.5,18 38,39 L 15,39 C 15,30 25,32.5 23,18
        body_points = [
            pt(22.0, 10.0), pt(24.8, 10.7), pt(27.7, 11.4), pt(30.0, 12.7),
            pt(32.3, 14.6), pt(34.0, 17.0), pt(35.6, 20.0), pt(36.7, 23.6),
            pt(37.5, 28.0), pt(37.9, 33.2), pt(38.0, 39.0), pt(15.0, 39.0),
            pt(15.3, 36.6), pt(16.0, 34.7), pt(17.1, 33.2), pt(18.3, 31.8),
            pt(19.8, 30.6), pt(21.2, 29.0), pt(22.2, 27.2), pt(22.9, 24.8),
            pt(23.3, 21.9), pt(23.2, 18.5),
        ]
        
        # Head polygon - sampled from bezier curve:
        # M 24,18 C 24.38,20.91 18.45,25.37 16,27 C 13,29 13.18,31.34 11,31
        # C 9.958,30.06 12.41,27.96 11,28 C 10,28 11.19,29.23 10,30
        # C 9,30 5.997,31 6,26 C 6,24 12,14 12,14 C 12,14 13.89,12.1 14,10.5
        # C 13.27,9.506 13.5,8.5 13.5,7.5 C 14.5,6.5 16.5,10 16.5,10
        # L 18.5,10 C 18.5,10 19.28,8.008 21,7 C 22,7 22,10 22,10
        head_points = [
            pt(24.0, 18.0), pt(24.3, 19.5), pt(23.7, 21.1), pt(22.5, 22.5),
            pt(20.9, 23.9), pt(18.8, 25.3), pt(16.0, 27.0), pt(14.4, 28.0),
            pt(12.9, 29.3), pt(11.7, 30.5), pt(11.0, 31.0), pt(10.6, 30.5),
            pt(11.0, 29.4), pt(11.3, 28.3), pt(11.0, 28.0), pt(10.6, 28.0),
            pt(10.6, 28.8), pt(10.3, 29.5), pt(10.0, 30.0), pt(9.2, 30.2),
            pt(7.5, 29.7), pt(6.2, 28.1), pt(6.0, 26.0), pt(6.0, 25.0),
            pt(7.0, 22.5), pt(8.5, 19.5), pt(10.2, 16.8), pt(11.5, 15.0),
            pt(12.0, 14.0), pt(12.0, 14.0), pt(12.5, 13.0), pt(13.2, 12.0),
            pt(13.7, 11.2), pt(14.0, 10.5), pt(13.8, 10.0), pt(13.6, 9.3),
            pt(13.5, 8.5), pt(13.5, 7.5), pt(14.0, 7.2), pt(15.0, 8.0),
            pt(16.0, 9.2), pt(16.5, 10.0), pt(18.5, 10.0), pt(18.5, 10.0),
            pt(19.0, 9.2), pt(19.8, 8.3), pt(21.0, 7.0), pt(21.3, 7.0),
            pt(21.7, 7.5), pt(22.0, 8.5), pt(22.0, 10.0),
        ]
        
        # Draw the main body shape
        draw.polygon(body_points, fill=line_color, outline=line_color)
        # Draw the head on top
        draw.polygon(head_points, fill=line_color, outline=line_color)
        
        # Eye - small filled circle (contrasting color)
        # Original SVG: ellipse at (9, 25.5) with radius 0.5
        eye_x, eye_y = pt(9, 25.5)
        eye_r = max(1, int(1.5 * s))
        eye_color = 0 if selected else 255
        draw.ellipse([eye_x - eye_r, eye_y - eye_r, eye_x + eye_r, eye_y + eye_r],
                    fill=eye_color, outline=eye_color)
        
        # Nostril - small ellipse (contrasting color)
        # Original SVG: rotated ellipse near (14.5, 15.5)
        nostril_x, nostril_y = pt(14, 16)
        nostril_r = max(1, int(1.2 * s))
        draw.ellipse([nostril_x - nostril_r, nostril_y - nostril_r,
                     nostril_x + nostril_r, nostril_y + nostril_r],
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
        """Draw a gear/cog icon.
        
        All drawing stays within the icon bounds (x-half to x+half, y-half to y+half).
        """
        half = size // 2
        # Teeth extend to edge, so shrink outer circle to leave room for teeth
        tooth_len = max(3, half // 6)  # Scale tooth length with size
        outer_r = half - tooth_len - 1  # Leave room for teeth within bounds
        inner_r = outer_r // 2
        
        draw.ellipse([x - outer_r, y - outer_r, x + outer_r, y + outer_r],
                    outline=line_color, width=2)
        draw.ellipse([x - inner_r, y - inner_r, x + inner_r, y + inner_r],
                    outline=line_color, width=2)
        
        # Gear teeth - extend from outer circle to edge of icon bounds
        for i in range(8):
            angle = i * (360 / 8) * (math.pi / 180)
            ix = x + int(outer_r * math.cos(angle))
            iy = y + int(outer_r * math.sin(angle))
            ox = x + int((half - 1) * math.cos(angle))
            oy = y + int((half - 1) * math.sin(angle))
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
    
    def _draw_engine_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                          size: int, line_color: int):
        """Draw an engine/CPU icon (circuit-like design)."""
        half = size // 2
        s = size / 36.0  # Scale factor
        
        # Central rectangle (chip body)
        chip_half = int(10*s)
        draw.rectangle([x - chip_half, y - chip_half, x + chip_half, y + chip_half],
                      outline=line_color, width=max(1, int(2*s)))
        
        # Pins on each side
        pin_len = int(4*s)
        pin_width = max(1, int(2*s))
        for offset in [-int(5*s), int(5*s)]:
            # Top pins
            draw.line([(x + offset, y - chip_half), (x + offset, y - chip_half - pin_len)],
                     fill=line_color, width=pin_width)
            # Bottom pins
            draw.line([(x + offset, y + chip_half), (x + offset, y + chip_half + pin_len)],
                     fill=line_color, width=pin_width)
            # Left pins
            draw.line([(x - chip_half, y + offset), (x - chip_half - pin_len, y + offset)],
                     fill=line_color, width=pin_width)
            # Right pins
            draw.line([(x + chip_half, y + offset), (x + chip_half + pin_len, y + offset)],
                     fill=line_color, width=pin_width)
    
    def _draw_elo_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                       size: int, line_color: int):
        """Draw an ELO/rating icon (chart/graph style)."""
        half = size // 2
        s = size / 36.0  # Scale factor
        
        # Draw bar chart style
        bar_width = int(6*s)
        gap = int(3*s)
        
        # Three bars of increasing height
        heights = [int(8*s), int(14*s), int(20*s)]
        start_x = x - int(12*s)
        base_y = y + int(10*s)
        
        for i, h in enumerate(heights):
            bx = start_x + i * (bar_width + gap)
            draw.rectangle([bx, base_y - h, bx + bar_width, base_y],
                          fill=line_color, outline=line_color)
        
        # Baseline
        draw.line([(x - half + int(2*s), base_y), (x + half - int(2*s), base_y)],
                 fill=line_color, width=max(1, int(2*s)))
    
    def _draw_color_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                         size: int, line_color: int):
        """Draw a color selection icon (half white, half black circle)."""
        half = size // 2
        s = size / 36.0  # Scale factor
        radius = int(14*s)
        
        # Draw circle outline
        draw.ellipse([x - radius, y - radius, x + radius, y + radius],
                    outline=line_color, width=max(1, int(2*s)))
        
        # Fill right half (simulate with arc/pie)
        # Draw a vertical line and fill the right semicircle
        draw.pieslice([x - radius, y - radius, x + radius, y + radius],
                     start=-90, end=90, fill=line_color)
    
    def _draw_king_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                        size: int, line_color: int, is_white: bool):
        """Draw a chess king icon.
        
        Args:
            is_white: If True, draw hollow (white piece), if False, draw filled (black piece)
        """
        half = size // 2
        s = size / 36.0  # Scale factor
        
        # Cross on top
        cross_width = max(1, int(2*s))
        cross_half = int(4*s)
        cross_top = y - half + int(2*s)
        
        # Vertical part of cross
        draw.line([(x, cross_top), (x, cross_top + int(8*s))],
                 fill=line_color, width=cross_width)
        # Horizontal part of cross
        draw.line([(x - cross_half, cross_top + int(3*s)), (x + cross_half, cross_top + int(3*s))],
                 fill=line_color, width=cross_width)
        
        # Crown body (bell shape)
        crown_top = y - int(6*s)
        crown_bottom = y + int(8*s)
        crown_width_top = int(6*s)
        crown_width_bottom = int(10*s)
        
        if is_white:
            # Hollow crown
            draw.polygon([
                (x - crown_width_top, crown_top),
                (x + crown_width_top, crown_top),
                (x + crown_width_bottom, crown_bottom),
                (x - crown_width_bottom, crown_bottom),
            ], outline=line_color)
        else:
            # Filled crown
            draw.polygon([
                (x - crown_width_top, crown_top),
                (x + crown_width_top, crown_top),
                (x + crown_width_bottom, crown_bottom),
                (x - crown_width_bottom, crown_bottom),
            ], fill=line_color)
        
        # Base
        base_y = y + int(10*s)
        base_half = int(12*s)
        draw.rectangle([x - base_half, base_y, x + base_half, base_y + int(4*s)],
                      fill=line_color if not is_white else None,
                      outline=line_color, width=max(1, int(1.5*s)))
    
    def _draw_random_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                          size: int, line_color: int):
        """Draw a random/dice icon."""
        half = size // 2
        s = size / 36.0  # Scale factor
        
        # Dice outline (slightly rotated rectangle effect via diamond)
        dice_half = int(12*s)
        draw.rectangle([x - dice_half, y - dice_half, x + dice_half, y + dice_half],
                      outline=line_color, width=max(1, int(2*s)))
        
        # Dice dots (6 pattern)
        dot_radius = int(2*s)
        dot_positions = [
            (-int(5*s), -int(5*s)),  # top-left
            (int(5*s), -int(5*s)),   # top-right
            (-int(5*s), 0),          # middle-left
            (int(5*s), 0),           # middle-right
            (-int(5*s), int(5*s)),   # bottom-left
            (int(5*s), int(5*s)),    # bottom-right
        ]
        
        for dx, dy in dot_positions:
            draw.ellipse([x + dx - dot_radius, y + dy - dot_radius,
                         x + dx + dot_radius, y + dy + dot_radius],
                        fill=line_color)
    
    def _draw_wifi_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                        size: int, line_color: int):
        """Draw a WiFi signal icon (concentric arcs)."""
        self._draw_wifi_signal_icon(draw, x, y, size, line_color, strength=3)
    
    def _draw_wifi_signal_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                               size: int, line_color: int, strength: int = 3):
        """Draw a WiFi signal icon with variable strength.
        
        Args:
            draw: ImageDraw object
            x: X center position
            y: Y center position
            size: Icon size in pixels
            line_color: Line color
            strength: Signal strength 1-3 (1=weak, 2=medium, 3=strong)
        """
        s = size / 36.0  # Scale factor
        
        # Draw concentric arcs from bottom center
        base_y = y + int(10*s)
        
        # Arc radii - draw all three but only fill based on strength
        radii = [int(6*s), int(12*s), int(18*s)]
        
        for i, radius in enumerate(radii):
            # Determine if this arc should be filled or just outlined
            if i < strength:
                # Active arc - full line
                width = max(1, int(3*s))
            else:
                # Inactive arc - thin dashed appearance (just outline)
                width = max(1, int(1*s))
            
            draw.arc([x - radius, base_y - radius, x + radius, base_y + radius],
                    start=225, end=315, fill=line_color, width=width)
        
        # Small dot at the bottom center (always drawn)
        dot_r = int(3*s)
        draw.ellipse([x - dot_r, base_y - dot_r, x + dot_r, base_y + dot_r],
                    fill=line_color)
    
    def _draw_system_icon(self, draw: ImageDraw.Draw, x: int, y: int,
                          size: int, line_color: int):
        """Draw a system/wrench icon."""
        half = size // 2
        s = size / 36.0  # Scale factor
        
        # Draw a wrench shape
        # Handle (diagonal rectangle)
        handle_width = int(4*s)
        draw.line([(x - int(10*s), y + int(10*s)), (x + int(4*s), y - int(4*s))],
                 fill=line_color, width=handle_width)
        
        # Wrench head (circular part with opening)
        head_x = x + int(6*s)
        head_y = y - int(6*s)
        head_r = int(8*s)
        draw.arc([head_x - head_r, head_y - head_r, head_x + head_r, head_y + head_r],
                start=45, end=315, fill=line_color, width=max(1, int(3*s)))
        
        # Opening of wrench
        draw.line([(head_x, head_y - head_r), (head_x + int(6*s), head_y - int(10*s))],
                 fill=line_color, width=max(1, int(2*s)))
        draw.line([(head_x + head_r, head_y), (head_x + int(10*s), head_y + int(6*s))],
                 fill=line_color, width=max(1, int(2*s)))
