#!/usr/bin/env python3
"""Tests for the new self-contained epaper framework."""

from __future__ import annotations

import asyncio
import unittest

from DGTCentaurMods.epaper.regions import Region, RegionSet
from DGTCentaurMods.epaper.framebuffer import FrameBuffer
from DGTCentaurMods.epaper.scheduler import AdaptiveRefreshPlanner, RefreshMode
from DGTCentaurMods.epaper.controller import EPaperController
from DGTCentaurMods.epaper.widgets.base import Widget
from DGTCentaurMods.epaper.driver import EPaperDriver


class RegionSetTest(unittest.TestCase):
    """RegionSet behaviors."""

    def test_merges_neighbors(self) -> None:
        """Regions that touch or overlap collapse into one bounding region."""
        regions = RegionSet()
        regions.add(Region(0, 0, 10, 10))
        regions.add(Region(9, 0, 5, 10))
        merged = regions.as_list()
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].width, 14)
        self.assertEqual(merged[0].height, 10)


class FrameBufferDiffTest(unittest.TestCase):
    """FrameBuffer diff detection."""

    def test_detects_dirty_patch(self) -> None:
        """Only the modified area is reported dirty."""
        base = FrameBuffer(width=32, height=32, background=255)
        updated = base.copy()
        updated.draw_rect(x=5, y=6, width=4, height=7, value=0)
        dirty = updated.diff(base)
        self.assertEqual(len(dirty.as_list()), 1)
        region = dirty.as_list()[0]
        self.assertEqual((region.x, region.y, region.width, region.height), (5, 6, 4, 7))


class RefreshPlannerTest(unittest.TestCase):
    """Refresh scheduling logic."""

    def test_promotes_full_refresh_after_budget(self) -> None:
        """Partial refresh budget forces a subsequent full refresh."""
        planner = AdaptiveRefreshPlanner(
            width=32,
            height=32,
            partial_budget=2,
            min_partial_area=4,
            max_regions=4,
            full_refresh_interval=10.0,
        )
        region = Region(0, 0, 8, 8)
        plan1 = planner.plan([region], fast_hint=False, timestamp=0.0)
        plan2 = planner.plan([region], fast_hint=False, timestamp=1.0)
        plan3 = planner.plan([region], fast_hint=False, timestamp=2.0)
        self.assertEqual(plan1.mode, RefreshMode.PARTIAL_BALANCED)
        self.assertEqual(plan2.mode, RefreshMode.PARTIAL_BALANCED)
        self.assertEqual(plan3.mode, RefreshMode.FULL)


class DummyDriver(EPaperDriver):
    """Driver mock capturing issued plans."""

    def __init__(self) -> None:
        self.plans: list = []

    async def refresh(self, plan, frame) -> None:  # type: ignore[override]
        self.plans.append((plan.mode, [r.as_tuple() for r in plan.regions]))


class DummyWidget(Widget):
    """Widget that toggles fill values when ticking."""

    def __init__(self, bounds: Region) -> None:
        super().__init__(bounds=bounds)
        self._state = 0

    async def tick(self, timestamp: float) -> None:  # type: ignore[override]
        self._state = (self._state + 1) % 2
        self.mark_dirty()

    async def render(self, canvas) -> None:  # type: ignore[override]
        value = 0 if self._state == 0 else 255
        canvas.fill(value)


class ControllerTest(unittest.TestCase):
    """Controller to driver interactions."""

    def test_controller_composes_and_calls_driver(self) -> None:
        """A cycle renders widgets, diffs and notifies driver."""
        driver = DummyDriver()
        controller = EPaperController(
            width=32,
            height=16,
            driver=driver,
            tick_interval=0.0,
        )
        controller.add_widget(DummyWidget(bounds=Region(0, 0, 16, 16)))

        async def run_cycle() -> None:
            await controller.update_once(timestamp=0.0)

        asyncio.run(run_cycle())
        self.assertTrue(driver.plans)
        mode, regions = driver.plans[0]
        self.assertIn(mode, {RefreshMode.PARTIAL_BALANCED, RefreshMode.FULL})
        self.assertTrue(regions)


if __name__ == "__main__":
    unittest.main()
