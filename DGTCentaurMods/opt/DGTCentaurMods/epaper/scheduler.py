"""Refresh planning logic for e-paper updates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List

from .regions import Region, RegionSet


class RefreshMode(Enum):
    """Available refresh waveforms."""

    IDLE = "idle"
    PARTIAL_FAST = "partial_fast"
    PARTIAL_BALANCED = "partial_balanced"
    FULL = "full"


@dataclass
class RefreshPlan:
    """Instruction for the driver layer."""

    mode: RefreshMode
    regions: List[Region]
    timestamp: float


class AdaptiveRefreshPlanner:
    """Chooses between partial and full refreshes."""

    def __init__(
        self,
        *,
        width: int,
        height: int,
        partial_budget: int,
        min_partial_area: int,
        max_regions: int,
        full_refresh_interval: float,
    ) -> None:
        self.width = width
        self.height = height
        self.partial_budget = max(1, partial_budget)
        self.min_partial_area = max(1, min_partial_area)
        self.max_regions = max(1, max_regions)
        self.full_refresh_interval = max(0.0, full_refresh_interval)
        self._partials_since_full = 0
        self._last_full_timestamp = 0.0

    def plan(
        self,
        regions: Iterable[Region],
        *,
        fast_hint: bool,
        timestamp: float,
    ) -> RefreshPlan:
        """Return next refresh plan."""
        merged = RegionSet()
        merged.extend(regions)
        active_regions = merged.as_list()
        if not active_regions:
            return RefreshPlan(RefreshMode.IDLE, [], timestamp)

        total_area = sum(region.area() for region in active_regions)
        if total_area < self.min_partial_area:
            bounding = merged.bounding_box()
            if bounding:
                active_regions = [bounding]

        active_regions = self._limit_regions(active_regions)

        full_due = self._should_force_full(total_area, timestamp)
        if full_due:
            self._partials_since_full = 0
            self._last_full_timestamp = timestamp
            return RefreshPlan(
                RefreshMode.FULL,
                [Region(0, 0, self.width, self.height)],
                timestamp,
            )

        self._partials_since_full += 1
        mode = RefreshMode.PARTIAL_FAST if fast_hint else RefreshMode.PARTIAL_BALANCED
        return RefreshPlan(mode, active_regions, timestamp)

    def _should_force_full(self, total_area: int, timestamp: float) -> bool:
        too_many_partials = self._partials_since_full >= self.partial_budget
        interval_due = self.full_refresh_interval > 0 and (
            timestamp - self._last_full_timestamp >= self.full_refresh_interval
        )
        big_change = total_area >= int(0.5 * self.width * self.height)
        return too_many_partials or interval_due or big_change

    def _limit_regions(self, regions: List[Region]) -> List[Region]:
        limited = list(regions)
        while len(limited) > self.max_regions:
            limited.sort(key=lambda r: r.area())
            first = limited.pop(0)
            second = limited.pop(0)
            limited.append(first.union(second))
        return limited

