"""Shadow framebuffer that tracks staged versus visible pixels."""

from __future__ import annotations

import threading
from typing import Optional

from PIL import Image, ImageChops

from .regions import Region
from .widgets import WidgetRender


class FrameBuffer:
    """Track staged pixels and compute dirty regions by diffing snapshots."""

    def __init__(self, width: int, height: int, *, background: int = 255) -> None:
        self._width = width
        self._height = height
        self._background = background
        self._staging = Image.new("L", (width, height), color=background)
        self._visible = self._staging.copy()
        self._dirty: list[Region] = []
        self._lock = threading.Lock()

    @property
    def width(self) -> int:
        """Return the display width."""
        return self._width

    @property
    def height(self) -> int:
        """Return the display height."""
        return self._height

    @property
    def image(self) -> Image.Image:
        """Return the staging image that contains the most recent frame."""
        return self._staging

    def apply(self, render: WidgetRender) -> Optional[Region]:
        """Apply a widget render and return the minimal changed region."""
        with self._lock:
            region = render.region.clamp(self._width, self._height)
            box = region.to_box()
            staged_crop = render.image
            visible_crop = self._visible.crop(box)
            diff = ImageChops.difference(staged_crop, visible_crop)
            bbox = diff.getbbox()
            self._staging.paste(staged_crop, box)
            if bbox is None:
                return None
            absolute = Region(
                region.x0 + bbox[0],
                region.y0 + bbox[1],
                region.x0 + bbox[2],
                region.y0 + bbox[3],
            ).clamp(self._width, self._height)
            self._dirty.append(absolute)
            return absolute

    def collect_dirty(self) -> list[Region]:
        """Return and clear the currently tracked dirty regions."""
        with self._lock:
            dirty, self._dirty = self._dirty, []
            return dirty

    def commit(self, region: Region) -> None:
        """Copy staged pixels into the visible snapshot for the region."""
        with self._lock:
            box = region.to_box()
            crop = self._staging.crop(box)
            self._visible.paste(crop, box)

    def snapshot(self) -> Image.Image:
        """Return a copy of the visible frame."""
        with self._lock:
            return self._visible.copy()

