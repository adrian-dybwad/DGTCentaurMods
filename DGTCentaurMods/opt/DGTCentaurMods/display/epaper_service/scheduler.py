from __future__ import annotations

import threading
from collections import deque
from concurrent.futures import Future
from typing import Deque, Optional

from PIL import Image

from .buffer import FrameBuffer
from .driver_base import DriverBase
from .regions import Region


class RefreshScheduler:
    """Background worker that flushes dirty regions via the driver."""

    def __init__(self, driver: DriverBase, framebuffer: FrameBuffer) -> None:
        self._driver = driver
        self._framebuffer = framebuffer
        self._thread = threading.Thread(target=self._loop, name="epaper-refresh", daemon=True)
        self._event = threading.Event()
        self._stop = threading.Event()
        self._queue: Deque[tuple[Optional[Region], Future]] = deque()
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._event.set()
        self._thread.join(timeout=2.0)

    def submit(self, region: Optional[Region], *, full: bool = False) -> Future:
        """
        Queues a refresh. If `full` is True, region is ignored and the entire buffer flushes.
        """
        future: Future = Future()
        with self._lock:
            if full:
                region = None
                # drop queued partials—full refresh supersedes them
                while self._queue:
                    pending = self._queue.popleft()
                    pending[1].set_result("skipped-by-full")
            self._queue.append((region, future))
        self._event.set()
        return future

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._event.wait()
            self._event.clear()
            batch: list[tuple[Optional[Region], Future]] = []
            with self._lock:
                while self._queue:
                    batch.append(self._queue.popleft())
            if not batch:
                continue
            # If any request demands a full refresh, perform one and settle all futures.
            if any(region is None for region, _ in batch):
                image = self._framebuffer.snapshot()
                self._driver.full_refresh(image)
                for _, fut in batch:
                    fut.set_result("full")
                continue
            # Otherwise merge regions and issue partials
            merged = _merge_regions([region for region, _ in batch if region is not None])
            for region in merged:
                expanded = _expand_region(region, self._driver.height)
                crop = self._framebuffer.snapshot().crop(expanded.to_box())
                self._driver.partial_refresh(expanded.y1, expanded.y2, crop)
            for _, fut in batch:
                fut.set_result("partial")


def _merge_regions(regions: list[Region]) -> list[Region]:
    if not regions:
        return []
    regions = sorted(regions, key=lambda r: (r.y1, r.x1))
    merged: list[Region] = [regions[0]]
    for current in regions[1:]:
        last = merged[-1]
        if _overlaps_vertically(last, current):
            merged[-1] = last.union(current)
        else:
            merged.append(current)
    return merged


def _overlaps_vertically(a: Region, b: Region) -> bool:
    return not (a.y2 < b.y1 or b.y2 < a.y1)


def _expand_region(region: Region, panel_height: int) -> Region:
    # Controller rows align to 8-pixel increments.
    row_height = 8
    y1 = max(0, (region.y1 // row_height) * row_height)
    y2 = min(panel_height, ((region.y2 + row_height - 1) // row_height) * row_height)
    return Region(region.x1, y1, region.x2, y2)

