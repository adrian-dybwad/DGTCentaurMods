"""Tests for the DGTCentaurMods.epaper framework."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.display.epaper_service.driver_base import DriverBase
from DGTCentaurMods.epaper.manager import DisplayManager
from DGTCentaurMods.epaper.regions import Region
from DGTCentaurMods.epaper.strategy import RefreshPolicy
from DGTCentaurMods.epaper.widgets import Widget


class FakeDriver(DriverBase):
    """In-memory driver used to assert refresh calls."""

    def __init__(self) -> None:
        self.partial_calls: list[dict[str, Any]] = []
        self.full_calls: list[dict[str, Any]] = []

    def init(self) -> None:
        """No-op init for the fake driver."""

    def reset(self) -> None:
        """No-op reset for the fake driver."""

    def full_refresh(self, image: Image.Image) -> None:
        """Record that a full refresh was requested."""
        self.full_calls.append({"image": image})

    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        """Record that a partial refresh was requested."""
        self.partial_calls.append({"y0": y0, "y1": y1, "image": image})

    def sleep(self) -> None:
        """No-op sleep for the fake driver."""

    def shutdown(self) -> None:
        """No-op shutdown for the fake driver."""

    def clear_calls(self) -> None:
        """Reset captured calls."""
        self.partial_calls.clear()
        self.full_calls.clear()


class TextWidget(Widget):
    """Widget used by the tests to simulate text updates."""

    _FONT = ImageFont.load_default()

    def __init__(self, region: Region, *, widget_id: str) -> None:
        super().__init__(region, widget_id=widget_id, z_index=0)
        self._text = ""

    def set_text(self, text: str) -> None:
        """Update the widget text and mark it dirty when it changes."""
        if text != self._text:
            self._text = text
            self.mark_dirty()

    def force_same_pixels(self) -> None:
        """Force a redraw without changing the rendered content."""
        self.mark_dirty()

    def build(self) -> Image.Image:
        """Render the current text to an image."""
        image = Image.new("L", self.region.size, 255)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, self.region.width, self.region.height), fill=255, outline=255)
        draw.text((0, 0), self._text, font=self._FONT, fill=0)
        return image


class DisplayManagerTests(unittest.TestCase):
    """Test suite covering the new DisplayManager orchestration."""

    def test_manager_performs_partial_refresh_for_dirty_widget(self) -> None:
        """Dirty widgets should result in a single partial refresh."""
        driver = FakeDriver()
        policy = RefreshPolicy()
        manager = DisplayManager(driver=driver, width=32, height=32, policy=policy)
        widget = TextWidget(Region(0, 0, 16, 16), widget_id="text")
        manager.add_widget(widget)

        widget.set_text("42")
        asyncio.run(manager.refresh_once())

        self.assertEqual(1, len(driver.partial_calls))
        self.assertEqual(0, len(driver.full_calls))
        first = driver.partial_calls[0]
        self.assertEqual(0, first["y0"])
        self.assertGreater(first["y1"], first["y0"])

    def test_manager_escalates_to_full_refresh_when_policy_requires(self) -> None:
        """Planner should opt for a full refresh when dirty regions exceed the threshold."""
        driver = FakeDriver()
        policy = RefreshPolicy(max_partial_regions=0, full_area_ratio=0.1)
        manager = DisplayManager(driver=driver, width=32, height=32, policy=policy)

        top = TextWidget(Region(0, 0, 32, 8), widget_id="top")
        bottom = TextWidget(Region(0, 24, 32, 32), widget_id="bottom")
        manager.add_widget(top)
        manager.add_widget(bottom)

        top.set_text("A")
        bottom.set_text("B")
        asyncio.run(manager.refresh_once())

        self.assertEqual(1, len(driver.full_calls))
        self.assertEqual(0, len(driver.partial_calls))

    def test_manager_skips_refresh_when_pixels_do_not_change(self) -> None:
        """No refresh should be sent when a widget redraws identical pixels."""
        driver = FakeDriver()
        policy = RefreshPolicy()
        manager = DisplayManager(driver=driver, width=32, height=32, policy=policy)
        widget = TextWidget(Region(0, 0, 16, 16), widget_id="stable")
        manager.add_widget(widget)

        widget.set_text("X")
        asyncio.run(manager.refresh_once())
        driver.clear_calls()

        widget.force_same_pixels()
        asyncio.run(manager.refresh_once())

        self.assertEqual([], driver.partial_calls)
        self.assertEqual([], driver.full_calls)


if __name__ == "__main__":
    unittest.main()


