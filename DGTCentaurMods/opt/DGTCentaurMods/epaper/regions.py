"""
Region management for tracking dirty areas on the display.
"""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Region:
    """
    Rectangular region with inclusive start (x1, y1) and exclusive end (x2, y2).
    """

    x1: int
    y1: int
    x2: int
    y2: int

    def clamp(self, width: int, height: int) -> "Region":
        """Clamp region to display bounds."""
        return Region(
            max(0, min(self.x1, width)),
            max(0, min(self.y1, height)),
            max(0, min(self.x2, width)),
            max(0, min(self.y2, height)),
        )

    def union(self, other: "Region") -> "Region":
        """Union of two regions."""
        return Region(
            min(self.x1, other.x1),
            min(self.y1, other.y1),
            max(self.x2, other.x2),
            max(self.y2, other.y2),
        )

    def intersects(self, other: "Region") -> bool:
        """Check if two regions intersect."""
        return not (self.x2 <= other.x1 or other.x2 <= self.x1 or
                    self.y2 <= other.y1 or other.y2 <= self.y1)

    def width(self) -> int:
        """Region width."""
        return max(0, self.x2 - self.x1)

    def height(self) -> int:
        """Region height."""
        return max(0, self.y2 - self.y1)

    def to_box(self) -> tuple[int, int, int, int]:
        """Convert to PIL box format (x1, y1, x2, y2)."""
        return (self.x1, self.y1, self.x2, self.y2)

    @staticmethod
    def full(width: int, height: int) -> "Region":
        """Create a full-screen region."""
        return Region(0, 0, width, height)


def merge_regions(regions: List[Region]) -> List[Region]:
    """
    Merge overlapping or adjacent regions.
    
    Regions are merged if they overlap vertically or are very close.
    """
    if not regions:
        return []

    # Sort by y1, then x1
    sorted_regions = sorted(regions, key=lambda r: (r.y1, r.x1))
    merged: List[Region] = [sorted_regions[0]]

    for current in sorted_regions[1:]:
        last = merged[-1]
        # Merge if vertically overlapping or very close (within 8 pixels)
        if _overlaps_vertically(last, current) or _close_vertically(last, current, threshold=8):
            merged[-1] = last.union(current)
        else:
            merged.append(current)

    return merged


def _overlaps_vertically(a: Region, b: Region) -> bool:
    """Check if regions overlap vertically."""
    return not (a.y2 < b.y1 or b.y2 < a.y1)


def _close_vertically(a: Region, b: Region, threshold: int) -> bool:
    """Check if regions are close vertically (for merging adjacent regions)."""
    if _overlaps_vertically(a, b):
        return True
    # Check if they're within threshold pixels vertically
    vertical_gap = min(abs(a.y2 - b.y1), abs(b.y2 - a.y1))
    return vertical_gap <= threshold


def expand_to_controller_alignment(region: Region, width: int, height: int) -> Region:
    """
    Expand region to align with controller row boundaries.
    
    The UC8151 controller requires:
    - Updates to be aligned to 8-pixel row boundaries vertically (required)
    - Horizontal alignment to byte boundaries (8 pixels) for efficiency
    
    Note: Waveshare DisplayPartial always refreshes full screen, so alignment
    is mainly for optimization and future true partial refresh support.
    """
    row_height = 8
    byte_width = 8
    
    # Expand vertically to 8-pixel row boundaries (required by controller)
    y1 = max(0, (region.y1 // row_height) * row_height)
    y2 = min(height, ((region.y2 + row_height - 1) // row_height) * row_height)
    
    # Expand horizontally to byte boundaries (8 pixels) for efficiency
    x1 = max(0, (region.x1 // byte_width) * byte_width)
    x2 = min(width, ((region.x2 + byte_width - 1) // byte_width) * byte_width)
    
    return Region(x1, y1, x2, y2)
