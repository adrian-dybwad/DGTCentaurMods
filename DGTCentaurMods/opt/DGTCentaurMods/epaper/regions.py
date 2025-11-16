"""Region utilities for describing dirty areas on the e-paper panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class Region:
    """Axis aligned rectangle on the framebuffer."""

    x: int
    y: int
    width: int
    height: int

    def as_tuple(self) -> Tuple[int, int, int, int]:
        """Return the region as an (x, y, width, height) tuple."""
        return (self.x, self.y, self.width, self.height)

    def area(self) -> int:
        """Area in pixels."""
        return self.width * self.height

    def intersects(self, other: "Region") -> bool:
        """Return True if the region overlaps the other region."""
        return not (
            self.x + self.width <= other.x
            or other.x + other.width <= self.x
            or self.y + self.height <= other.y
            or other.y + other.height <= self.y
        )

    def touches(self, other: "Region") -> bool:
        """Return True if regions overlap or touch (sharing an edge)."""
        horizontal_gap = max(other.x - (self.x + self.width), self.x - (other.x + other.width))
        vertical_gap = max(other.y - (self.y + self.height), self.y - (other.y + other.height))
        return horizontal_gap <= 0 and vertical_gap <= 0

    def union(self, other: "Region") -> "Region":
        """Return the minimal bounding region covering both regions."""
        min_x = min(self.x, other.x)
        min_y = min(self.y, other.y)
        max_x = max(self.x + self.width, other.x + other.width)
        max_y = max(self.y + self.height, other.y + other.height)
        return Region(min_x, min_y, max_x - min_x, max_y - min_y)


class RegionSet:
    """Mutable collection of merged dirty regions."""

    def __init__(self) -> None:
        self._regions: List[Region] = []

    def add(self, region: Region) -> None:
        """Insert region, merging overlapping/touching regions."""
        if region.width <= 0 or region.height <= 0:
            return

        queue = [region]
        while queue:
            candidate = queue.pop()
            merged = False
            for idx, existing in enumerate(self._regions):
                if candidate.touches(existing):
                    queue.append(candidate.union(existing))
                    self._regions.pop(idx)
                    merged = True
                    break
            if not merged:
                self._regions.append(candidate)

    def extend(self, regions: Iterable[Region]) -> None:
        """Add multiple regions."""
        for region in regions:
            self.add(region)

    def is_empty(self) -> bool:
        """True when no regions are tracked."""
        return not self._regions

    def as_list(self) -> List[Region]:
        """Return the merged regions."""
        return list(self._regions)

    def bounding_box(self) -> Optional[Region]:
        """Return one region covering all tracked regions."""
        if not self._regions:
            return None
        region = self._regions[0]
        for current in self._regions[1:]:
            region = region.union(current)
        return region

