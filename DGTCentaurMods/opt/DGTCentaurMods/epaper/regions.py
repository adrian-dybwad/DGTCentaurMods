"""
Region management for ePaper display updates.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class Region:
    """Represents a rectangular region on the display."""
    x1: int  # Left (inclusive)
    y1: int  # Top (inclusive)
    x2: int  # Right (exclusive)
    y2: int  # Bottom (exclusive)
    
    def __post_init__(self):
        if self.x1 >= self.x2 or self.y1 >= self.y2:
            raise ValueError(f"Invalid region: {self}")
    
    def intersects(self, other: 'Region') -> bool:
        """Check if this region intersects with another."""
        return not (self.x2 <= other.x1 or self.x1 >= other.x2 or
                   self.y2 <= other.y1 or self.y1 >= other.y2)
    
    def union(self, other: 'Region') -> 'Region':
        """Return the union of this region with another."""
        return Region(
            min(self.x1, other.x1),
            min(self.y1, other.y1),
            max(self.x2, other.x2),
            max(self.y2, other.y2)
        )


def merge_regions(regions: List[Region]) -> List[Region]:
    """Merge overlapping regions."""
    if not regions:
        return []
    
    merged = []
    for region in sorted(regions, key=lambda r: (r.x1, r.y1)):
        if not merged:
            merged.append(region)
        else:
            last = merged[-1]
            if last.intersects(region):
                merged[-1] = last.union(region)
            else:
                merged.append(region)
    
    return merged


def expand_to_byte_alignment(region: Region, width: int, height: int) -> Region:
    """Expand region to align with byte boundaries (8 pixels)."""
    byte_width = 8
    
    x1 = max(0, (region.x1 // byte_width) * byte_width)
    x2 = min(width, ((region.x2 + byte_width - 1) // byte_width) * byte_width)
    y1 = max(0, region.y1)
    y2 = min(height, region.y2)
    
    return Region(x1, y1, x2, y2)
