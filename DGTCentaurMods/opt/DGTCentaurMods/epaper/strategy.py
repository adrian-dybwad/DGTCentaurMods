"""Refresh planning logic for the e-paper display."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .regions import Region, merge_regions

RefreshMode = Literal["partial", "full"]


@dataclass
class RefreshPolicy:
    """Configuration knobs that control refresh planning."""

    max_partial_regions: int = 4
    max_partials_before_full: int = 10
    full_area_ratio: float = 0.6
    merge_padding: int = 2
    band_padding: int = 2


@dataclass
class RefreshPlan:
    """Single refresh request emitted by the planner."""

    mode: RefreshMode
    region: Region


class RefreshPlanner:
    """Convert dirty regions into optimized refresh plans."""

    def __init__(self, policy: RefreshPolicy, width: int, height: int) -> None:
        self._policy = policy
        self._width = width
        self._height = height
        self._partials_since_full = 0

    def build_plans(self, regions: list[Region]) -> list[RefreshPlan]:
        """Create refresh plans for the supplied dirty regions."""
        if not regions:
            return []
        merged = merge_regions(regions, padding=self._policy.merge_padding)
        if self._requires_full_refresh(merged):
            self._partials_since_full = 0
            return [RefreshPlan(mode="full", region=Region.full(self._width, self._height))]
        plans: list[RefreshPlan] = []
        for region in merged:
            padded = region.inflate(self._policy.band_padding).clamp(self._width, self._height)
            band = Region(0, padded.y0, self._width, padded.y1)
            plans.append(RefreshPlan(mode="partial", region=band))
        self._partials_since_full += len(plans)
        return plans

    def _requires_full_refresh(self, regions: list[Region]) -> bool:
        """Return True when a full refresh is required."""
        total_area = sum(region.area() for region in regions)
        panel_area = self._width * self._height
        area_ratio = total_area / panel_area if panel_area else 0.0
        if area_ratio >= self._policy.full_area_ratio:
            return True
        if len(regions) > self._policy.max_partial_regions:
            return True
        if self._partials_since_full >= self._policy.max_partials_before_full:
            return True
        return False

