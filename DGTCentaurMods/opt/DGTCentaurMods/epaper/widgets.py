"""Widget base classes shared by all e-paper UI components."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from PIL import Image  # type: ignore[import]

from .regions import Region


@dataclass
class WidgetRender:
    """Renderable payload produced by a widget."""

    region: Region
    image: Image.Image


class Widget(ABC):
    """Base class for all widgets that can live on the e-paper surface."""

    def __init__(self, region: Region, *, widget_id: Optional[str] = None, z_index: int = 0) -> None:
        self._region = region
        self._widget_id = widget_id or self.__class__.__name__
        self._z_index = z_index
        self._dirty = True
        self._lock = threading.Lock()

    @property
    def region(self) -> Region:
        """Return the region reserved by the widget."""
        return self._region

    @property
    def id(self) -> str:
        """Return the identifier used to register the widget."""
        return self._widget_id

    @property
    def z_index(self) -> int:
        """Return the stacking order for the widget."""
        return self._z_index

    def mark_dirty(self) -> None:
        """Mark the widget as needing to repaint."""
        with self._lock:
            self._dirty = True

    def render(self) -> Optional[WidgetRender]:
        """Render the widget if it is dirty."""
        with self._lock:
            if not self._dirty:
                return None
            image = self.build()
            if image.size != self._region.size:
                raise ValueError(
                    f"Widget {self._widget_id} returned image {image.size} "
                    f"that does not match region {self._region.size}"
                )
            self._dirty = False
            return WidgetRender(region=self._region, image=image)

    @abstractmethod
    def build(self) -> Image.Image:
        """Return a freshly rendered image for the widget."""

