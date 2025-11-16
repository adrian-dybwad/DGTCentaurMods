"""Digital clock widget."""

from __future__ import annotations

from datetime import datetime

from .base import Widget
from ..framebuffer import CanvasView
from ..regions import Region


class DigitalClockWidget(Widget):
    """Shows a 24-hour clock updated every second."""

    def __init__(self, *, bounds: Region, scale: int = 5) -> None:
        super().__init__(bounds=bounds, name="Clock")
        self.scale = max(1, scale)
        self._last_value = ""

    async def tick(self, timestamp: float) -> None:  # type: ignore[override]
        """Update the time string once per second."""
        value = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
        if value != self._last_value:
            self._last_value = value
            self.mark_dirty(fast=True)

    async def render(self, canvas: CanvasView) -> None:  # type: ignore[override]
        """Draw the clock digits."""
        canvas.fill(255)
        canvas.draw_text(
            0,
            max(0, (self.bounds.height - 5 * self.scale) // 2),
            self._last_value,
            scale=self.scale,
            value=0,
            spacing=self.scale,
        )

