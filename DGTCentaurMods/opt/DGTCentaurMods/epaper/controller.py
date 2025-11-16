"""High-level orchestration of widgets, framebuffer, and refresh planner."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Optional

from .driver import EPaperDriver
from .framebuffer import FrameBuffer
from .regions import Region
from .scheduler import AdaptiveRefreshPlanner, RefreshMode
from .widgets.base import Widget

LOGGER = logging.getLogger(__name__)


class EPaperController:
    """Coordinates widget rendering and driver refreshes."""

    def __init__(
        self,
        *,
        width: int,
        height: int,
        driver: EPaperDriver,
        planner: Optional[AdaptiveRefreshPlanner] = None,
        background: int = 0,
        tick_interval: float = 0.5,
    ) -> None:
        self.width = width
        self.height = height
        self.driver = driver
        self.tick_interval = max(0.0, tick_interval)
        self._planner = planner or AdaptiveRefreshPlanner(
            width=width,
            height=height,
            partial_budget=6,
            min_partial_area=64,
            max_regions=8,
            full_refresh_interval=30.0,
        )
        self._frame = FrameBuffer(width=width, height=height, background=background)
        self._widgets: List[Widget] = []
        self._running = False
        self._first_refresh = True

    def add_widget(self, widget: Widget) -> None:
        """Register a widget."""
        self._validate_bounds(widget.bounds)
        self._widgets.append(widget)

    def remove_widget(self, widget: Widget) -> None:
        """Remove a widget if present."""
        if widget in self._widgets:
            self._widgets.remove(widget)

    async def update_once(self, timestamp: Optional[float] = None) -> None:
        """Run a single update cycle."""
        if timestamp is None:
            timestamp = time.monotonic()
        staging = self._frame.copy()
        fast_hint = False

        for widget in self._widgets:
            await widget.tick(timestamp)
            if not widget.is_dirty:
                continue
            canvas = staging.canvas_for(widget.bounds)
            await widget.render(canvas)
            widget.clear_dirty()
            fast_hint = fast_hint or widget.consume_fast_hint()

        dirty_regions = staging.diff(self._frame)
        if dirty_regions.is_empty():
            LOGGER.debug("No changes detected for timestamp %.3f", timestamp)
            self._frame = staging
            return

        plan = self._planner.plan(dirty_regions.as_list(), fast_hint=fast_hint, timestamp=timestamp)
        if plan.mode is RefreshMode.IDLE:
            self._frame = staging
            return

        LOGGER.debug("Issuing refresh mode=%s regions=%d", plan.mode, len(plan.regions))
        await self.driver.refresh(plan, staging)
        self._frame = staging

    async def run(self) -> None:
        """Continuously update the display until cancelled."""
        self._running = True
        await self.driver.connect()
        try:
            while self._running:
                await self.update_once()
                if self.tick_interval > 0:
                    await asyncio.sleep(self.tick_interval)
        finally:
            await self.driver.close()

    def stop(self) -> None:
        """Signal the run loop to exit."""
        self._running = False

    def _validate_bounds(self, region: Region) -> None:
        if region.x < 0 or region.y < 0:
            raise ValueError("Widget bounds must be within the framebuffer.")
        if region.x + region.width > self.width or region.y + region.height > self.height:
            raise ValueError("Widget bounds exceed framebuffer.")

