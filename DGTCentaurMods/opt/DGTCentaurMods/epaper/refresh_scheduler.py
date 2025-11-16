"""
Refresh scheduler that queues and executes display updates.
"""

import threading
import time
from collections import deque
from concurrent.futures import Future
from typing import Deque, List, Optional

from PIL import Image

from .driver import Driver
from .framebuffer import FrameBuffer
from .regions import Region, expand_to_controller_alignment, merge_regions


class RefreshScheduler:
    """
    Background worker that schedules and executes display refreshes.
    
    Handles:
    - Queueing refresh requests
    - Merging overlapping regions
    - Expanding regions to controller alignment
    - Deciding between partial and full refreshes
    - Throttling to prevent display overload
    """

    def __init__(self, driver: Driver, framebuffer: FrameBuffer) -> None:
        self._driver = driver
        self._framebuffer = framebuffer
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._queue: Deque[tuple[Optional[Region], Future]] = deque()
        self._lock = threading.Lock()
        self._partial_refresh_count = 0
        self._last_full_refresh = time.time()
        
        # After N partial refreshes, force a full refresh to clear ghosting
        self._max_partial_refreshes = 50
        
        # Minimum time between refreshes (ms)
        self._min_refresh_interval = 0.1

    def start(self) -> None:
        """Start the scheduler thread."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="epaper-refresh-scheduler",
            daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler thread and wait for completion."""
        if self._thread is None:
            return
        self._stop_event.set()
        self._wake_event.set()
        self._thread.join(timeout=5.0)
        self._thread = None

    def submit(self, region: Optional[Region] = None, *, full: bool = False) -> Future:
        """
        Submit a refresh request.
        
        Args:
            region: Specific region to refresh (None for full screen)
            full: If True, force a full refresh regardless of region
        
        Returns:
            Future that completes when the refresh is done
        """
        future: Future = Future()
        
        with self._lock:
            if full:
                # Full refresh supersedes all queued partials
                region = None
                # Cancel all pending partial refreshes
                while self._queue:
                    pending_region, pending_future = self._queue.popleft()
                    if not pending_future.done():
                        pending_future.set_result("skipped-by-full")
            
            self._queue.append((region, future))
        
        self._wake_event.set()
        return future

    def _run(self) -> None:
        """Main scheduler loop."""
        while not self._stop_event.is_set():
            self._wake_event.wait(timeout=1.0)
            self._wake_event.clear()
            
            if self._stop_event.is_set():
                break
            
            # Process queued refresh requests
            batch: List[tuple[Optional[Region], Future]] = []
            with self._lock:
                while self._queue:
                    batch.append(self._queue.popleft())
            
            if not batch:
                continue
            
            # Check if we need a full refresh
            needs_full = (
                any(region is None for region, _ in batch) or
                self._partial_refresh_count >= self._max_partial_refreshes or
                (time.time() - self._last_full_refresh) > 300  # Force full every 5 minutes
            )
            
            if needs_full:
                self._execute_full_refresh(batch)
            else:
                self._execute_partial_refreshes(batch)

    def _execute_full_refresh(self, batch: List[tuple[Optional[Region], Future]]) -> None:
        """Execute a full screen refresh."""
        image = self._framebuffer.snapshot()
        
        try:
            self._driver.full_refresh(image)
            self._framebuffer.flush_all()
            self._partial_refresh_count = 0
            self._last_full_refresh = time.time()
            
            # Complete all futures
            for _, future in batch:
                if not future.done():
                    future.set_result("full")
        except Exception as e:
            # Mark futures as failed
            for _, future in batch:
                if not future.done():
                    future.set_exception(e)

    def _execute_partial_refreshes(self, batch: List[tuple[Optional[Region], Future]]) -> None:
        """Execute partial refreshes for the given regions."""
        # Extract regions (filter out None)
        regions = [region for region, _ in batch if region is not None]
        
        if not regions:
            # No regions to refresh, just complete futures
            for _, future in batch:
                if not future.done():
                    future.set_result("no-op")
            return
        
        # Merge overlapping regions
        merged = merge_regions(regions)
        
        # Execute each merged region
        for region in merged:
            # Expand to controller alignment
            expanded = expand_to_controller_alignment(
                region,
                self._driver.width,
                self._driver.height
            )
            
            # Get image for this region
            image = self._framebuffer.snapshot_region(expanded)
            
            try:
                # Calculate hardware coordinates (y0, y1 from bottom)
                y0 = self._driver.height - expanded.y2
                y1 = self._driver.height - expanded.y1
                
                self._driver.partial_refresh(y0, y1, image)
                
                # Mark region as flushed
                self._framebuffer.flush_region(expanded)
                self._partial_refresh_count += 1
                
                # Small delay between partial refreshes
                time.sleep(self._min_refresh_interval)
                
            except Exception as e:
                # If partial refresh fails, mark all futures as failed
                for _, future in batch:
                    if not future.done():
                        future.set_exception(e)
                return
        
        # Complete all futures
        for _, future in batch:
            if not future.done():
                future.set_result("partial")

