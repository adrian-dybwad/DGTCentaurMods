from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Optional

from PIL import Image, ImageDraw

from .regions import Region


class FrameBuffer:
    """Owns the working image and tracks dirty regions."""

    def __init__(self, width: int = 128, height: int = 296) -> None:
        self.width = width
        self.height = height
        self._image = Image.new("1", (self.width, self.height), 255)
        self._lock = threading.RLock()
        self._dirty: Optional[Region] = None

    @property
    def image(self) -> Image.Image:
        return self._image

    def snapshot(self) -> Image.Image:
        with self._lock:
            return self._image.copy()

    def snapshot_region(self, region: Region) -> Image.Image:
        with self._lock:
            return self._image.crop(region.clamp(self.width, self.height).to_box())

    def mark_dirty(self, region: Region) -> None:
        with self._lock:
            bounded = region.clamp(self.width, self.height)
            if self._dirty is None:
                self._dirty = bounded
            else:
                self._dirty = self._dirty.union(bounded)

    def consume_dirty(self) -> Optional[Region]:
        with self._lock:
            region = self._dirty
            self._dirty = None
            return region

    @contextmanager
    def acquire_canvas(self):
        """
        Provides a drawing context and a helper to report the damaged region.

        Usage:
            with framebuffer.acquire_canvas() as canvas:
                draw = canvas.draw
                draw.rectangle(...)
                canvas.mark_dirty(Region(...))
        """

        with self._lock:
            draw = ImageDraw.Draw(self._image)
            recorder = _DamageRecorder(self.width, self.height)
            yield Canvas(self, draw, recorder)
            if recorder.region is not None:
                self._dirty = recorder.region.union(self._dirty) if self._dirty else recorder.region


class _DamageRecorder:
    def __init__(self, width: int, height: int) -> None:
        self.region: Optional[Region] = None
        self._width = width
        self._height = height

    def mark(self, region: Region) -> None:
        bounded = region.clamp(self._width, self._height)
        if self.region is None:
            self.region = bounded
        else:
            self.region = self.region.union(bounded)


class Canvas:
    """Wrapper exposed by FrameBuffer.acquire_canvas."""

    def __init__(self, framebuffer: FrameBuffer, draw: ImageDraw.ImageDraw, recorder: _DamageRecorder) -> None:
        self._framebuffer = framebuffer
        self._draw = draw
        self._recorder = recorder

    @property
    def image(self) -> Image.Image:
        return self._framebuffer.image

    @property
    def draw(self) -> ImageDraw.ImageDraw:
        return self._draw

    def mark_dirty(self, region: Region) -> None:
        self._recorder.mark(region)

