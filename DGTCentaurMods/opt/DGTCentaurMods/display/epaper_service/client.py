from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from PIL import Image

from .buffer import FrameBuffer, Canvas
from .driver_base import DriverBase
from .drivers.native import NativeDriver
from .drivers.proxy import ProxyDriver
from .drivers.simulator import SimulatorDriver
from .regions import Region
from .scheduler import RefreshScheduler


class EpaperService:
    """High-level façade used by the rest of the project."""

    def __init__(self) -> None:
        self._framebuffer = FrameBuffer()
        self._driver: Optional[DriverBase] = None
        self._scheduler: Optional[RefreshScheduler] = None
        self._initialized = False

    @property
    def size(self) -> tuple[int, int]:
        return (self._framebuffer.width, self._framebuffer.height)

    def init(self, driver: str | None = None) -> None:
        from DGTCentaurMods.board.logging import log
        log.info(f">>> EpaperService.init() ENTERED, _initialized={self._initialized}")
        if self._initialized:
            log.info(">>> EpaperService.init() already initialized, RETURNING EARLY")
            return
        backend = driver or os.environ.get("EPAPER_DRIVER", "native")
        log.info(f">>> EpaperService.init() backend={backend}")
        self._driver = _driver_factory(backend)
        log.info(">>> EpaperService.init() driver created, calling reset()")
        self._driver.reset()
        log.info(">>> EpaperService.init() reset() complete, calling driver.init()")
        self._driver.init()
        log.info(">>> EpaperService.init() driver.init() complete, creating RefreshScheduler")
        self._scheduler = RefreshScheduler(self._driver, self._framebuffer)
        log.info(">>> EpaperService.init() RefreshScheduler created, starting scheduler")
        self._scheduler.start()
        log.info(">>> EpaperService.init() scheduler started, clearing buffer")
        # Clear both buffer and physical panel so we never show stale frames on boot.
        region = Region.full(self._framebuffer.width, self._framebuffer.height)
        with self._framebuffer.acquire_canvas() as canvas:
            canvas.draw.rectangle(region.to_box(), fill=255, outline=255)
            canvas.mark_dirty(region)
        log.info(">>> EpaperService.init() buffer cleared, submitting full refresh")
        self.submit_full(await_completion=True)
        log.info(">>> EpaperService.init() full refresh complete, setting _initialized=True")
        self._initialized = True
        log.info(">>> EpaperService.init() EXITING")

    def shutdown(self) -> None:
        """
        Shutdown the e-paper service.
        
        All 5 agents agreed: Must flush ALL dirty regions in a loop, not just one.
        This ensures all pending updates are displayed before sleep/shutdown.
        """
        if not self._initialized:
            return
        assert self._scheduler and self._driver
        from DGTCentaurMods.board.logging import log
        # Flush ALL remaining dirty regions before shutdown (not just one)
        # This ensures all pending updates are displayed before sleep/shutdown
        log.info(">>> EpaperService.shutdown() flushing all dirty regions")
        flush_count = 0
        while True:
            dirty = self._framebuffer.consume_dirty()
            if dirty is None:
                break
            flush_count += 1
            log.info(f">>> EpaperService.shutdown() flushing dirty region #{flush_count}: {dirty}")
            future = self._scheduler.submit(dirty)
            future.result()  # Wait for refresh to complete
        if flush_count > 0:
            log.info(f">>> EpaperService.shutdown() flushed {flush_count} dirty region(s)")
        else:
            log.info(">>> EpaperService.shutdown() no dirty regions to flush")
        # All 4 agents agreed: Wait for scheduler queue to drain before stopping
        # This ensures all pending refresh operations complete
        log.info(">>> EpaperService.shutdown() waiting for scheduler queue to drain")
        self._await_scheduler_queue_drain()
        self._scheduler.stop()
        # Wait for any pending refresh operations to complete before sleep/shutdown
        self._driver.sleep()
        self._driver.shutdown()
        self._initialized = False
        log.info(">>> EpaperService.shutdown() complete")

    @contextmanager
    def acquire_canvas(self) -> Iterator[Canvas]:
        if not self._initialized:
            self.init()
        with self._framebuffer.acquire_canvas() as canvas:
            yield canvas

    def submit_region(self, region: Region, *, await_completion: bool = False) -> None:
        if not self._scheduler:
            raise RuntimeError("ePaper service not initialized")
        future = self._scheduler.submit(region)
        if await_completion:
            future.result()

    def submit_full(self, *, await_completion: bool = False) -> None:
        from DGTCentaurMods.board.logging import log
        log.warning("EpaperService.submit_full() called - will cause flashing refresh")
        if not self._scheduler:
            raise RuntimeError("ePaper service not initialized")
        future = self._scheduler.submit(None, full=True)
        if await_completion:
            future.result()

    def push_image(self, image: Image.Image, *, full: bool = False) -> None:
        if not self._driver:
            raise RuntimeError("ePaper service not initialized")
        if full:
            self._driver.full_refresh(image)
        else:
            self._driver.partial_refresh(0, self._driver.height, image)

    def await_idle(self) -> None:
        if not self._scheduler:
            return
        future = self._scheduler.submit(None, full=False)
        future.result()

    def await_all_pending(self) -> None:
        """
        Wait for all pending refresh operations to complete.
        
        This ensures that any queued refreshes (partial or full) are completed
        before submitting new refresh operations, preventing race conditions.
        """
        from DGTCentaurMods.board.logging import log
        if not self._scheduler:
            return
        # Submit a dummy request and wait for it to complete
        # This ensures all previous requests in the queue are processed first
        log.info(">>> EpaperService.await_all_pending() waiting for all pending refreshes")
        future = self._scheduler.submit(None, full=False)
        try:
            future.result(timeout=10.0)  # Wait up to 10 seconds
            log.info(">>> EpaperService.await_all_pending() all pending refreshes complete")
        except Exception as e:
            log.warning(f">>> EpaperService.await_all_pending() timeout or error: {e}")

    def _await_scheduler_queue_drain(self) -> None:
        """
        Wait for scheduler queue to drain completely.
        
        All 4 agents agreed: Must wait for queue to drain before stopping scheduler
        to prevent loss of pending refresh operations.
        """
        from DGTCentaurMods.board.logging import log
        if not self._scheduler:
            return
        # Check if queue is empty by submitting a dummy request and waiting
        # This ensures all previous requests are processed
        future = self._scheduler.submit(None, full=False)
        try:
            future.result(timeout=10.0)  # Wait up to 10 seconds for queue to drain
            log.info(">>> EpaperService._await_scheduler_queue_drain() queue drained")
        except Exception as e:
            log.warning(f">>> EpaperService._await_scheduler_queue_drain() timeout or error: {e}")

    def snapshot(self) -> Image.Image:
        return self._framebuffer.snapshot()

    def blit(self, image: Image.Image, x: int = 0, y: int = 0) -> None:
        region = Region(x, y, x + image.width, y + image.height)
        with self.acquire_canvas() as canvas:
            canvas.image.paste(image, (x, y))
            canvas.mark_dirty(region)
        self.submit_region(region)


def _driver_factory(name: str) -> DriverBase:
    normalized = name.lower()
    if normalized == "native":
        return NativeDriver()
    if normalized == "proxy":
        return ProxyDriver()
    if normalized == "simulator":
        return SimulatorDriver()
    raise ValueError(f"Unknown EPAPER driver '{name}'")

