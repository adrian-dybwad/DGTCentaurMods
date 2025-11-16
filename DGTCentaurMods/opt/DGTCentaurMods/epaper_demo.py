#!/usr/bin/env python3
"""Demonstration of the autonomous e-paper framework."""

from __future__ import annotations

import asyncio
import logging
import random
import sys
import time
from pathlib import Path


def _ensure_package_on_path() -> None:
    """Guarantee the DGTCentaurMods package is importable when run directly."""
    package_dir = Path(__file__).resolve().parent
    root = package_dir.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_ensure_package_on_path()

from DGTCentaurMods.epaper import EPaperController, SimulatedEPaperDriver
from DGTCentaurMods.epaper.regions import Region
from DGTCentaurMods.epaper.widgets import BatteryWidget, DigitalClockWidget, MessageWidget

LOGGER = logging.getLogger(__name__)


class BatteryModel:
    """Toy model that drifts up/down to mimic battery changes."""

    def __init__(self) -> None:
        self._level = 80

    def level(self) -> int:
        """Return the next pseudo level."""
        delta = random.choice([-2, -1, 0, 1])
        self._level = max(5, min(100, self._level + delta))
        return self._level


async def run_demo(duration: float = 30.0) -> None:
    """Run the e-paper demo for the specified duration."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    driver = SimulatedEPaperDriver(latency=0.01)
    controller = EPaperController(
        width=296,
        height=128,
        driver=driver,
        tick_interval=1.0,
        background=255,
    )
    battery_model = BatteryModel()

    controller.add_widget(
        DigitalClockWidget(bounds=Region(0, 0, 200, 32), scale=5),
    )
    controller.add_widget(
        BatteryWidget(bounds=Region(210, 0, 80, 32), level_provider=battery_model.level, update_interval=12.0),
    )
    controller.add_widget(
        MessageWidget(
            bounds=Region(0, 40, 296, 40),
            messages=["Centaur Mods", "E-paper demo", "Widgets in sync"],
            interval=5.0,
            scale=3,
        )
    )

    await driver.connect()
    start = time.monotonic()
    try:
        while time.monotonic() - start < duration:
            await controller.update_once()
            await asyncio.sleep(controller.tick_interval or 1.0)
    finally:
        await driver.close()

    LOGGER.info("Demo finished. Issued %d refreshes.", len(driver.history))


if __name__ == "__main__":
    asyncio.run(run_demo())

