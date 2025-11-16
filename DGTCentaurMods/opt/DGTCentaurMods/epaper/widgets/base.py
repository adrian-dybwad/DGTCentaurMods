"""Widget abstractions for the e-paper framework."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..framebuffer import CanvasView
from ..regions import Region


class Widget(ABC):
    """Base class for drawable widgets."""

    def __init__(self, *, bounds: Region, name: str | None = None) -> None:
        self.bounds = bounds
        self.name = name or self.__class__.__name__
        self._dirty = True
        self._fast_hint = False

    @property
    def is_dirty(self) -> bool:
        """True when the widget requires re-rendering."""
        return self._dirty

    def mark_dirty(self, *, fast: bool = False) -> None:
        """Flag the widget as dirty, optionally hinting for fast refresh."""
        self._dirty = True
        self._fast_hint = self._fast_hint or fast

    def consume_fast_hint(self) -> bool:
        """Return True if a fast refresh was requested."""
        fast = self._fast_hint
        self._fast_hint = False
        return fast

    def clear_dirty(self) -> None:
        """Reset the dirty flag."""
        self._dirty = False

    async def tick(self, timestamp: float) -> None:
        """Update internal state. Override to add per-cycle behavior."""

    @abstractmethod
    async def render(self, canvas: CanvasView) -> None:
        """Draw onto the provided canvas."""

