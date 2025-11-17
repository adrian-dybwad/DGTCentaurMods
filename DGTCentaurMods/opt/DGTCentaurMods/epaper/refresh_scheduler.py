"""
Refresh scheduler that queues and executes display updates using true partial refreshes.
"""

import threading
import time
from collections import deque
from concurrent.futures import Future
from typing import Deque, List, Optional

from .driver import Driver
from .framebuffer import FrameBuffer
from .regions import Region, expand_to_controller_alignment, merge_regions


class RefreshScheduler:
    """
    Background worker that schedules and executes display refreshes.
    
    Uses true partial updates to refresh only changed regions, minimizing
    flicker and update time.
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
        
        # Minimum time between refreshes (prevents hardware overload)
        self._min_refresh_interval = 0.05  # 50ms minimum

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
        
        # Cancel pending requests
        with self._lock:
            while self._queue:
                _, future = self._queue.popleft()
                if not future.done():
                    future.set_result("cancelled-on-shutdown")
        
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
                while self._queue:
                    pending_region, pending_future = self._queue.popleft()
                    if not pending_future.done():
                        pending_future.set_result("skipped-by-full")
            
            # Limit queue size to prevent memory buildup
            max_queue_size = 10
            if len(self._queue) >= max_queue_size and not full:
                future.set_result("skipped-queue-full")
                return future
            
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
            time_since_full = time.time() - self._last_full_refresh
            has_full_request = any(region is None for region, _ in batch)
            needs_full = (
                has_full_request or
                self._partial_refresh_count >= self._max_partial_refreshes or
                time_since_full > 300  # Force full every 5 minutes
            )
            
            if needs_full:
                if has_full_request:
                    print(f"Full refresh requested explicitly")
                elif self._partial_refresh_count >= self._max_partial_refreshes:
                    print(f"Full refresh: reached max partial refreshes ({self._partial_refresh_count})")
                elif time_since_full > 300:
                    print(f"Full refresh: time since last full ({time_since_full:.1f}s) > 300s")
                self._execute_full_refresh(batch)
            else:
                self._execute_partial_refreshes(batch)

    def _execute_full_refresh(self, batch: List[tuple[Optional[Region], Future]]) -> None:
        """Execute a full screen refresh."""
        try:
            image = self._framebuffer.snapshot()
            self._driver.full_refresh(image)
            self._framebuffer.flush_all()
            self._partial_refresh_count = 0
            self._last_full_refresh = time.time()
            
            for _, future in batch:
                if not future.done():
                    future.set_result("full")
        except Exception as e:
            for _, future in batch:
                if not future.done():
                    future.set_exception(e)

    def _execute_partial_refreshes(self, batch: List[tuple[Optional[Region], Future]]) -> None:
        """Execute true partial refreshes for the given regions."""
        regions = [region for region, _ in batch if region is not None]
        
        if not regions:
            for _, future in batch:
                if not future.done():
                    future.set_result("no-op")
            return
        
        if self._stop_event.is_set():
            for _, future in batch:
                if not future.done():
                    future.set_result("cancelled-on-shutdown")
            return
        
        # Merge overlapping regions
        merged = merge_regions(regions)
        print(f"Executing {len(merged)} partial refresh(es) for {len(regions)} region(s)")
        
        # Get full-screen snapshot once
        full_image = self._framebuffer.snapshot()
        
        # Execute partial refresh for each merged region
        for region in merged:
            if self._stop_event.is_set():
                break
            
            # Expand to controller alignment (byte boundaries)
            expanded = expand_to_controller_alignment(
                region,
                self._driver.width,
                self._driver.height
            )
            
            try:
                # Use true partial refresh - only refreshes the expanded region
                self._driver.partial_refresh(
                    expanded.x1,
                    expanded.y1,
                    expanded.x2,
                    expanded.y2,
                    full_image
                )
                
                # Mark the expanded region as flushed
                self._framebuffer.flush_region(expanded)
                self._partial_refresh_count += 1
                
                # Small delay between partial refreshes
                if not self._stop_event.is_set():
                    time.sleep(self._min_refresh_interval)
                
            except Exception as e:
                print(f"ERROR in partial refresh: {e}")
                import traceback
                traceback.print_exc()
                # Don't fail the whole batch - just log and continue
                # The exception might be transient
                continue
        
        # Complete all futures
        for _, future in batch:
            if not future.done():
                future.set_result("partial")
