"""Battery indicator widget."""

from __future__ import annotations

from typing import Callable

from .base import Widget
from ..framebuffer import CanvasView
from ..regions import Region


class BatteryWidget(Widget):
    """Simple horizontal battery with periodic sampling."""

    def __init__(
        self,
        *,
        bounds: Region,
        level_provider: Callable[[], int],
        update_interval: float = 15.0,
    ) -> None:
        super().__init__(bounds=bounds, name="Battery")
        self._provider = level_provider
        self._update_interval = max(0.1, update_interval)
        self._last_level = 100
        self._last_update = float("-inf")

    async def tick(self, timestamp: float) -> None:  # type: ignore[override]
        """Sample the provider and refresh if the level changed."""
        if timestamp - self._last_update < self._update_interval:
            return
        self._last_update = timestamp
        raw_level = max(0, min(100, int(self._provider())))
        if raw_level != self._last_level:
            self._last_level = raw_level
            self.mark_dirty()

    async def render(self, canvas: CanvasView) -> None:  # type: ignore[override]
        """Draw the battery outline, fill, and text percentage."""
        canvas.fill(255)
        body_width = max(6, self.bounds.width - 6)
        body_height = max(6, self.bounds.height - 4)
        # Outline
        canvas.draw_rect(0, 0, body_width, body_height, 0)
        canvas.draw_rect(1, 1, body_width - 2, body_height - 2, 255)
        # Tip
        tip_height = max(4, body_height // 3)
        tip_x = body_width
        tip_y = (body_height - tip_height) // 2
        canvas.draw_rect(tip_x, tip_y, 4, tip_height, 0)
        canvas.draw_rect(tip_x + 1, tip_y + 1, 2, max(1, tip_height - 2), 255)

        fill_width = int((body_width - 4) * (self._last_level / 100.0))
        canvas.draw_rect(2, 2, fill_width, body_height - 4, 0)
        canvas.draw_text(
            4,
            max(0, (body_height - 5) // 2),
            f"{self._last_level:02d}%",
            scale=1,
            value=0,
        )

