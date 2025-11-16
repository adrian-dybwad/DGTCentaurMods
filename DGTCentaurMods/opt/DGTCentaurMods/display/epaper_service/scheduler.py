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
            panel_width = getattr(self._driver, "width", self._framebuffer.width)
            panel_height = getattr(self._driver, "height", self._framebuffer.height)
            # If any request demands a full refresh, perform one and settle all futures.
            if any(region is None for region, _ in batch):
                from DGTCentaurMods.board.logging import log
                import time
                log.info(">>> RefreshScheduler._loop() FULL REFRESH: Taking snapshot")
                start_time = time.time()
                image = self._framebuffer.snapshot()
                log.info(f">>> RefreshScheduler._loop() FULL REFRESH: Snapshot taken, size={image.size}, mode={image.mode}")
                
                # Verify framebuffer content before refresh
                pixels = list(image.getdata())
                non_white_pixels = sum(1 for p in pixels if p != 255)
                log.info(f">>> RefreshScheduler._loop() FULL REFRESH: Framebuffer verification: {non_white_pixels} non-white pixels out of {len(pixels)} total")
                
                # Sample specific regions to verify content
                # Status bar region (top 16 pixels)
                status_region = image.crop((0, 0, 128, 16))
                status_pixels = list(status_region.getdata())
                status_non_white = sum(1 for p in status_pixels if p != 255)
                log.info(f">>> RefreshScheduler._loop() FULL REFRESH: Status bar region (y=0 to 16): {status_non_white} non-white pixels")
                
                # Middle region (menu area typically)
                middle_region = image.crop((0, 16, 128, 200))
                middle_pixels = list(middle_region.getdata())
                middle_non_white = sum(1 for p in middle_pixels if p != 255)
                log.info(f">>> RefreshScheduler._loop() FULL REFRESH: Middle region (y=16 to 200): {middle_non_white} non-white pixels")
                
                rotated = _rotate_180(image)
                log.info(">>> RefreshScheduler._loop() FULL REFRESH: Calling driver.full_refresh()")
                driver_start = time.time()
                try:
                    self._driver.full_refresh(rotated)
                    driver_duration = time.time() - driver_start
                    log.info(f">>> RefreshScheduler._loop() FULL REFRESH: driver.full_refresh() returned after {driver_duration:.3f}s")
                    # Only resolve futures AFTER hardware refresh completes
                    for _, fut in batch:
                        fut.set_result("full")
                except RuntimeError as e:
                    log.error(f">>> RefreshScheduler._loop() FULL REFRESH: driver.full_refresh() failed: {e}")
                    # Mark futures as failed instead of crashing
                    for _, fut in batch:
                        if not fut.done():
                            fut.set_exception(e)
                total_duration = time.time() - start_time
                log.info(f">>> RefreshScheduler._loop() FULL REFRESH: Complete, total duration={total_duration:.3f}s")
                continue
            # Otherwise merge regions and issue partials
            merged = _merge_regions([region for region, _ in batch if region is not None])
            from DGTCentaurMods.board.logging import log
            for region in merged:
                expanded = _expand_region(region, panel_width, panel_height)
                crop = self._framebuffer.snapshot().crop(expanded.to_box())
                rotated = _rotate_180(crop)
                y0 = panel_height - expanded.y2
                y1 = panel_height - expanded.y1
                try:
                    self._driver.partial_refresh(y0, y1, rotated)
                except RuntimeError as e:
                    log.error(f">>> RefreshScheduler._loop() partial_refresh() failed: {e}")
                    # Mark futures as failed instead of crashing
                    for _, fut in batch:
                        if not fut.done():
                            fut.set_exception(e)
                    continue
            for _, fut in batch:
                if not fut.done():
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


def _expand_region(region: Region, panel_width: int, panel_height: int) -> Region:
    # Controller rows align to 8-pixel increments.
    row_height = 8
    y1 = max(0, (region.y1 // row_height) * row_height)
    y2 = min(panel_height, ((region.y2 + row_height - 1) // row_height) * row_height)
    return Region(0, y1, panel_width, y2)


def _rotate_180(image: Image.Image) -> Image.Image:
    """Rotate the logical buffer to match the panel orientation."""
    return image.transpose(Image.ROTATE_180)

