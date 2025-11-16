"""Framebuffer abstractions and drawing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .regions import Region, RegionSet


class FrameBuffer:
    """In-memory grayscale framebuffer."""

    def __init__(self, width: int, height: int, background: int = 255) -> None:
        self.width = width
        self.height = height
        self.background = background
        self._pixels: List[List[int]] = [
            [background for _ in range(self.width)] for _ in range(self.height)
        ]

    def copy(self) -> "FrameBuffer":
        """Return a deep copy."""
        clone = FrameBuffer(self.width, self.height, self.background)
        clone._pixels = [row[:] for row in self._pixels]
        return clone

    def fill(self, value: int) -> None:
        """Fill entire framebuffer."""
        self._validate_value(value)
        for row in self._pixels:
            for idx in range(self.width):
                row[idx] = value

    def draw_rect(self, x: int, y: int, width: int, height: int, value: int) -> None:
        """Draw a filled rectangle."""
        self._validate_value(value)
        min_x = max(x, 0)
        min_y = max(y, 0)
        max_x = min(x + width, self.width)
        max_y = min(y + height, self.height)
        if min_x >= max_x or min_y >= max_y:
            return
        for row in range(min_y, max_y):
            for col in range(min_x, max_x):
                self._pixels[row][col] = value

    def canvas_for(self, region: Region) -> "CanvasView":
        """Return a view that clamps drawing to the region."""
        return CanvasView(self, region)

    def diff(self, other: "FrameBuffer") -> RegionSet:
        """Return dirty regions compared to another framebuffer."""
        if self.width != other.width or self.height != other.height:
            raise ValueError("FrameBuffer dimensions must match when diffing.")
        regions = RegionSet()
        for y in range(self.height):
            for x in range(self.width):
                if self._pixels[y][x] != other._pixels[y][x]:
                    regions.add(Region(x, y, 1, 1))
        return regions

    def get_pixels(self) -> List[List[int]]:
        """Expose pixel data for drivers."""
        return [row[:] for row in self._pixels]

    def _validate_value(self, value: int) -> None:
        """Ensure grayscale values remain within byte range."""
        if value < 0 or value > 255:
            raise ValueError("Pixel value must be 0–255")


@dataclass
class CanvasView:
    """Helper passed to widgets to constrain drawing operations."""

    framebuffer: FrameBuffer
    region: Region

    def fill(self, value: int) -> None:
        """Fill the entire region."""
        self.framebuffer.draw_rect(self.region.x, self.region.y, self.region.width, self.region.height, value)

    def draw_rect(self, x: int, y: int, width: int, height: int, value: int) -> None:
        """Draw a rectangle relative to the view."""
        self.framebuffer.draw_rect(
            self.region.x + x,
            self.region.y + y,
            width,
            height,
            value,
        )

    def draw_text(
        self,
        x: int,
        y: int,
        text: str,
        *,
        scale: int = 1,
        value: int = 0,
        spacing: int = 1,
    ) -> None:
        """Draw monospaced text using the built-in 5×3 font."""
        cursor_x = x
        for char in text.upper():
            glyph = _BUILTIN_FONT.get(char, _BUILTIN_FONT["?"])
            self._blit_glyph(cursor_x, y, glyph, scale, value)
            cursor_x += (len(glyph[0]) * scale) + spacing

    def _blit_glyph(
        self,
        x: int,
        y: int,
        glyph: List[str],
        scale: int,
        value: int,
    ) -> None:
        """Render a glyph at the requested location."""
        for row_idx, row in enumerate(glyph):
            for col_idx, pixel in enumerate(row):
                if pixel != "#":
                    continue
                px = self.region.x + x + col_idx * scale
                py = self.region.y + y + row_idx * scale
                self.framebuffer.draw_rect(px, py, scale, scale, value)


_BUILTIN_FONT = {
    "0": [
        "###",
        "# #",
        "# #",
        "# #",
        "###",
    ],
    "1": [
        " ##",
        "# #",
        "  #",
        "  #",
        " ###",
    ],
    "2": [
        "###",
        "  #",
        "###",
        "#  ",
        "###",
    ],
    "3": [
        "###",
        "  #",
        " ##",
        "  #",
        "###",
    ],
    "4": [
        "# #",
        "# #",
        "###",
        "  #",
        "  #",
    ],
    "5": [
        "###",
        "#  ",
        "###",
        "  #",
        "###",
    ],
    "6": [
        "###",
        "#  ",
        "###",
        "# #",
        "###",
    ],
    "7": [
        "###",
        "  #",
        "  #",
        "  #",
        "  #",
    ],
    "8": [
        "###",
        "# #",
        "###",
        "# #",
        "###",
    ],
    "9": [
        "###",
        "# #",
        "###",
        "  #",
        "###",
    ],
    ":": [
        "   ",
        " # ",
        "   ",
        " # ",
        "   ",
    ],
    "%": [
        "#  ",
        "  #",
        " # ",
        "#  ",
        "  #",
    ],
    "?": [
        "###",
        "  #",
        " ##",
        "   ",
        " # ",
    ],
    "A": [
        "###",
        "# #",
        "###",
        "# #",
        "# #",
    ],
    "B": [
        "## ",
        "# #",
        "## ",
        "# #",
        "## ",
    ],
    "C": [
        "###",
        "#  ",
        "#  ",
        "#  ",
        "###",
    ],
    "D": [
        "## ",
        "# #",
        "# #",
        "# #",
        "## ",
    ],
    "E": [
        "###",
        "#  ",
        "## ",
        "#  ",
        "###",
    ],
    "F": [
        "###",
        "#  ",
        "## ",
        "#  ",
        "#  ",
    ],
    "G": [
        "###",
        "#  ",
        "# #",
        "# #",
        "###",
    ],
    "H": [
        "# #",
        "# #",
        "###",
        "# #",
        "# #",
    ],
    "I": [
        "###",
        " # ",
        " # ",
        " # ",
        "###",
    ],
    "L": [
        "#  ",
        "#  ",
        "#  ",
        "#  ",
        "###",
    ],
    "M": [
        "# #",
        "###",
        "###",
        "# #",
        "# #",
    ],
    "N": [
        "## ",
        "## ",
        "# #",
        "# #",
        "# #",
    ],
    "O": [
        "###",
        "# #",
        "# #",
        "# #",
        "###",
    ],
    "P": [
        "###",
        "# #",
        "###",
        "#  ",
        "#  ",
    ],
    "R": [
        "###",
        "# #",
        "###",
        "## ",
        "# #",
    ],
    "S": [
        "###",
        "#  ",
        "###",
        "  #",
        "###",
    ],
    "T": [
        "###",
        " # ",
        " # ",
        " # ",
        " # ",
    ],
    "U": [
        "# #",
        "# #",
        "# #",
        "# #",
        "###",
    ],
    "V": [
        "# #",
        "# #",
        "# #",
        "# #",
        " # ",
    ],
    "Y": [
        "# #",
        "# #",
        " # ",
        " # ",
        " # ",
    ],
    " ": [
        "   ",
        "   ",
        "   ",
        "   ",
        "   ",
    ],
}

