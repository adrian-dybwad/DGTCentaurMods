#!/usr/bin/env python3
"""Demonstration of the autonomous e-paper framework."""

from __future__ import annotations

import argparse
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

from DGTCentaurMods.epaper import (  # pylint: disable=wrong-import-position
    EPaperController,
    NativeEPaperDriver,
    SimulatedEPaperDriver,
)
from DGTCentaurMods.epaper.regions import Region  # pylint: disable=wrong-import-position
from DGTCentaurMods.epaper.widgets import (  # pylint: disable=wrong-import-position
    BatteryWidget,
    DigitalClockWidget,
    MessageWidget,
)

LOGGER = logging.getLogger(__name__)
PANEL_WIDTH = 296
PANEL_HEIGHT = 128


class BatteryModel:
    """Toy model that drifts up/down to mimic battery changes."""

    def __init__(self) -> None:
        self._level = 80

    def level(self) -> int:
        """Return the next pseudo level."""
        delta = random.choice([-2, -1, 0, 1])
        self._level = max(5, min(100, self._level + delta))
        return self._level


def _build_driver(mode: str, simulate_latency: float) -> SimulatedEPaperDriver | NativeEPaperDriver:
    if mode == "simulate":
        LOGGER.info("Using simulated driver with latency %.3fs", simulate_latency)
        return SimulatedEPaperDriver(latency=simulate_latency)
    LOGGER.info("Using native hardware driver.")
    return NativeEPaperDriver(width=PANEL_WIDTH, height=PANEL_HEIGHT)


async def run_demo(*, duration: float, driver_mode: str, simulate_latency: float) -> None:
    """Run the e-paper demo for the specified duration."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    driver = _build_driver(driver_mode, simulate_latency)
    controller = EPaperController(
        width=PANEL_WIDTH,
        height=PANEL_HEIGHT,
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="E-paper controller demonstration.")
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="How long to run the demo (seconds).",
    )
    parser.add_argument(
        "--driver",
        choices=["hardware", "simulate"],
        default="hardware",
        help="Select the driver backend.",
    )
    parser.add_argument(
        "--simulate-latency",
        type=float,
        default=0.01,
        help="Simulated driver latency (seconds).",
    )
    return parser.parse_args()


async def _async_main() -> None:
    args = _parse_args()
    await run_demo(duration=args.duration, driver_mode=args.driver, simulate_latency=args.simulate_latency)


if __name__ == "__main__":
    asyncio.run(_async_main())

