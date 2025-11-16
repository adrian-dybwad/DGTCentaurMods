"""Demonstration script for the DGTCentaurMods e-paper framework."""

from __future__ import annotations

import asyncio
import itertools
import pathlib
import sys
from datetime import datetime
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont  # type: ignore[import]

# Ensure the repository root (which contains the DGTCentaurMods package) is importable
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.display.epaper_service.drivers.simulator import SimulatorDriver
from DGTCentaurMods.epaper import DisplayManager, RefreshPolicy, Widget
from DGTCentaurMods.epaper.regions import Region


class TextWidget(Widget):
    """Simple text widget that prints a string within its region."""

    region: Region
    label: str
    font: ImageFont.ImageFont

    def __init__(self, region: Region, *, label: str, widget_id: str, z_index: int = 0) -> None:
        super().__init__(region, widget_id=widget_id, z_index=z_index)
        self.region = region
        self.label = label
        self.font = ImageFont.load_default()
        self._value = ""

    def set_value(self, value: str) -> None:
        """Update the displayed value."""
        if value != self._value:
            self._value = value
            self.mark_dirty()

    def build(self) -> Image.Image:
        """Render the widget content."""
        image = Image.new("L", self.region.size, 255)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, self.region.width, self.region.height), fill=255, outline=0)
        draw.text((2, 0), f"{self.label}: {self._value}", font=self.font, fill=0)
        return image


class ProgressWidget(Widget):
    """Displays a horizontal progress bar that can be updated externally."""

    def __init__(self, region: Region, *, widget_id: str, z_index: int = 0) -> None:
        super().__init__(region, widget_id=widget_id, z_index=z_index)
        self._ratio = 0.0

    def set_ratio(self, ratio: float) -> None:
        """Update the progress ratio."""
        ratio = max(0.0, min(1.0, ratio))
        if ratio != self._ratio:
            self._ratio = ratio
            self.mark_dirty()

    def build(self) -> Image.Image:
        """Render the progress bar."""
        image = Image.new("L", self.region.size, 255)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, self.region.width, self.region.height), outline=0, width=1)
        fill_width = int(self.region.width * self._ratio)
        draw.rectangle((1, 1, fill_width, self.region.height - 1), fill=0)
        return image


async def drive_widgets(clock: TextWidget, counter: TextWidget, ticker: TextWidget, progress: ProgressWidget) -> None:
    """Update widget content once per second."""
    statuses = itertools.cycle(["IDLE", "THINKING", "READY", "SYNCING"])
    step = 0
    while True:
        clock.set_value(datetime.now().strftime("%H:%M:%S"))
        counter.set_value(f"{step:04d}")
        ticker.set_value(next(statuses))
        progress.set_ratio((step % 10) / 10.0)
        step += 1
        await asyncio.sleep(1.0)


async def main() -> None:
    """Entry point for the demo."""
    log.info("Starting e-paper demo")
    driver = SimulatorDriver()
    driver.reset()
    driver.init()

    policy = RefreshPolicy(max_partial_regions=4, max_partials_before_full=12, full_area_ratio=0.75, band_padding=2)
    manager = DisplayManager(driver=driver, width=128, height=296, policy=policy)

    clock = TextWidget(Region(0, 0, 128, 24), label="Clock", widget_id="clock")
    counter = TextWidget(Region(0, 30, 128, 54), label="Counter", widget_id="counter")
    ticker = TextWidget(Region(0, 60, 128, 84), label="Status", widget_id="status")
    progress = ProgressWidget(Region(0, 100, 128, 120), widget_id="progress")

    for widget in _iter_widgets(clock, counter, ticker, progress):
        manager.add_widget(widget)

    updater = asyncio.create_task(drive_widgets(clock, counter, ticker, progress), name="widget-updater")
    runner = asyncio.create_task(manager.run(poll_interval=1.0), name="display-manager")

    try:
        await asyncio.sleep(300)  # Run for five minutes or until interrupted.
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        log.info("Demo interrupted by user")
    finally:
        updater.cancel()
        runner.cancel()
        await asyncio.gather(updater, runner, return_exceptions=True)
        driver.sleep()
        driver.shutdown()
        log.info("E-paper demo stopped")


def _iter_widgets(*widgets: Widget) -> Iterable[Widget]:
    """Iterate over all provided widgets."""
    return widgets


if __name__ == "__main__":
    asyncio.run(main())

