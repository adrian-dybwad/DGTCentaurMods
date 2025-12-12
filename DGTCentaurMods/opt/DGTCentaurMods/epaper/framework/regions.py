"""
Region class for widget positioning and overlap detection.
"""

from dataclasses import dataclass


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
