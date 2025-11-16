"""Message carousel widget."""

from __future__ import annotations

from typing import Iterable, List

from .base import Widget
from ..framebuffer import CanvasView
from ..regions import Region


class MessageWidget(Widget):
    """Cycles through predefined text messages."""

    def __init__(
        self,
        *,
        bounds: Region,
        messages: Iterable[str],
        interval: float = 5.0,
        scale: int = 2,
    ) -> None:
        super().__init__(bounds=bounds, name="Message")
        items = [msg.upper() for msg in messages]
        if not items:
            raise ValueError("MessageWidget requires at least one message.")
        self._messages: List[str] = items
        self._interval = max(0.5, interval)
        self._scale = max(1, scale)
        self._index = 0
        self._last_switch = 0.0

    async def tick(self, timestamp: float) -> None:  # type: ignore[override]
        """Advance to the next message after the configured interval."""
        if timestamp - self._last_switch < self._interval:
            return
        self._last_switch = timestamp
        self._index = (self._index + 1) % len(self._messages)
        self.mark_dirty()

    async def render(self, canvas: CanvasView) -> None:  # type: ignore[override]
        """Draw the current message centered vertically."""
        canvas.fill(255)
        text = self._messages[self._index]
        canvas.draw_text(
            0,
            max(0, (self.bounds.height - 5 * self._scale) // 2),
            text,
            scale=self._scale,
            value=0,
            spacing=self._scale,
        )

