"""Async display manager that orchestrates widgets and refreshes."""

from __future__ import annotations

import asyncio
from typing import Dict, List, Sequence

from PIL import Image

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.display.epaper_service.driver_base import DriverBase

from .framebuffer import FrameBuffer
from .regions import Region
from .strategy import RefreshPlan, RefreshPlanner, RefreshPolicy
from .widgets import Widget


class DisplayManager:
    """High-level orchestrator that keeps the e-paper display in sync."""

    def __init__(self, driver: DriverBase, *, width: int, height: int, policy: RefreshPolicy | None = None) -> None:
        self._driver = driver
        self._framebuffer = FrameBuffer(width, height)
        self._planner = RefreshPlanner(policy or RefreshPolicy(), width, height)
        self._widgets: Dict[str, Widget] = {}

    def add_widget(self, widget: Widget) -> None:
        """Register a widget with the manager."""
        if widget.id in self._widgets:
            raise ValueError(f"Widget with id '{widget.id}' already registered")
        clamped_region = widget.region.clamp(self._framebuffer.width, self._framebuffer.height)
        if clamped_region != widget.region:
            raise ValueError(f"Widget '{widget.id}' region exceeds framebuffer bounds")
        self._widgets[widget.id] = widget
        log.info("DisplayManager.add_widget(%s)", widget.id)

    def remove_widget(self, widget_id: str) -> None:
        """Remove a widget from the manager."""
        if widget_id in self._widgets:
            log.info("DisplayManager.remove_widget(%s)", widget_id)
            del self._widgets[widget_id]

    async def refresh_once(self) -> None:
        """Render dirty widgets once and push necessary refreshes."""
        regions = self._collect_regions()
        if not regions:
            return
        plans = self._planner.build_plans(regions)
        for plan in plans:
            if plan.mode == "full":
                await self._push_full()
            else:
                await self._push_partial(plan.region)

    async def run(self, poll_interval: float = 1.0) -> None:
        """Continuously refresh widgets at the requested cadence."""
        while True:
            await self.refresh_once()
            await asyncio.sleep(poll_interval)

    def snapshot(self) -> Image.Image:
        """Return the currently visible frame."""
        return self._framebuffer.snapshot()

    def _collect_regions(self) -> List[Region]:
        """Render dirty widgets and collect the resulting regions."""
        ordered: Sequence[Widget] = sorted(self._widgets.values(), key=lambda w: (w.z_index, w.id))
        regions: List[Region] = []
        for widget in ordered:
            render = widget.render()
            if not render:
                continue
            changed = self._framebuffer.apply(render)
            if changed:
                regions.append(changed)
        return regions

    async def _push_full(self) -> None:
        """Send a full refresh to the driver."""
        region = Region.full(self._framebuffer.width, self._framebuffer.height)
        await self._run_blocking(self._driver.full_refresh, self._framebuffer.image)
        self._framebuffer.commit(region)
        log.info("DisplayManager._push_full refreshed entire panel")

    async def _push_partial(self, region: Region) -> None:
        """Send a partial refresh to the driver."""
        await self._run_blocking(self._driver.partial_refresh, region.y0, region.y1, self._framebuffer.image)
        self._framebuffer.commit(region)
        log.info("DisplayManager._push_partial refreshed rows %s-%s", region.y0, region.y1)

    async def _run_blocking(self, func, *args) -> None:
        """Execute a blocking driver call in the default executor."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, func, *args)

