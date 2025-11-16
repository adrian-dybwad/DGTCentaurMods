"""Region primitives and utilities used by the e-paper display manager."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Region:
    """Axis-aligned rectangle defined in panel coordinates."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        """Return the width of the region."""
        return max(0, self.x1 - self.x0)

    @property
    def height(self) -> int:
        """Return the height of the region."""
        return max(0, self.y1 - self.y0)

    @property
    def size(self) -> tuple[int, int]:
        """Return the (width, height) of the region."""
        return (self.width, self.height)

    def area(self) -> int:
        """Return the number of pixels covered by the region."""
        return self.width * self.height

    def to_box(self) -> tuple[int, int, int, int]:
        """Return a PIL-compatible bounding box tuple."""
        return (self.x0, self.y0, self.x1, self.y1)

    def intersects(self, other: Region) -> bool:
        """Return True when this region overlaps another region."""
        return not (
            self.x1 <= other.x0
            or self.x0 >= other.x1
            or self.y1 <= other.y0
            or self.y0 >= other.y1
        )

    def merge(self, other: Region) -> Region:
        """Return a region that covers this region and another region."""
        return Region(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def inflate(self, padding: int) -> Region:
        """Return a new region expanded by padding in all directions."""
        return Region(self.x0 - padding, self.y0 - padding, self.x1 + padding, self.y1 + padding)

    def clamp(self, width: int, height: int) -> Region:
        """Return a version of the region clamped to the provided bounds."""
        return Region(
            max(0, min(self.x0, width)),
            max(0, min(self.y0, height)),
            max(0, min(self.x1, width)),
            max(0, min(self.y1, height)),
        )

    @classmethod
    def full(cls, width: int, height: int) -> Region:
        """Return a region that covers the entire panel."""
        return cls(0, 0, width, height)

    @classmethod
    def from_box(cls, box: tuple[int, int, int, int]) -> Region:
        """Create a region from a PIL-style bounding box."""
        return cls(*box)


def merge_regions(regions: list[Region], *, padding: int = 0) -> list[Region]:
    """Merge overlapping or adjacent regions using the provided padding."""
    if not regions:
        return []
    expanded = [region.inflate(padding) for region in regions]
    expanded.sort(key=lambda r: (r.y0, r.x0))
    merged: list[Region] = []
    current = expanded[0]
    for region in expanded[1:]:
        if current.intersects(region):
            current = current.merge(region)
            continue
        merged.append(current)
        current = region
    merged.append(current)
    # Remove the temporary padding before returning.
    normalized = [Region(r.x0 + padding, r.y0 + padding, r.x1 - padding, r.y1 - padding) for r in merged]
    return normalized

