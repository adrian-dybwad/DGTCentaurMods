from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    """Inclusive-exclusive rectangle describing damaged area."""

    x1: int
    y1: int
    x2: int
    y2: int

    def clamp(self, width: int, height: int) -> "Region":
        return Region(
            max(0, min(self.x1, width)),
            max(0, min(self.y1, height)),
            max(0, min(self.x2, width)),
            max(0, min(self.y2, height)),
        )

    def union(self, other: "Region") -> "Region":
        return Region(
            min(self.x1, other.x1),
            min(self.y1, other.y1),
            max(self.x2, other.x2),
            max(self.y2, other.y2),
        )

    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    def to_box(self) -> tuple[int, int, int, int]:
        return (self.x1, self.y1, self.x2, self.y2)

    @staticmethod
    def full(width: int, height: int) -> "Region":
        return Region(0, 0, width, height)

