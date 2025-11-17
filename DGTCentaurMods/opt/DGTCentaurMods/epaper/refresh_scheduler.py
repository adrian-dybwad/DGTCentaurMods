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
        self._last_partial_refresh_time = 0.0
        
        # After N partial refreshes, force a full refresh to clear ghosting
        # Industry standard is 8-10 partial refreshes before full refresh
        # For fast-moving content, use fewer partial refreshes to prevent ghosting
        # Reduced to 3 to prevent ghosting from frequent updates
        self._max_partial_refreshes = 3
        
        # Minimum time between refreshes (in seconds)
        # Prevents display overload by spacing out refresh operations
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
        """
        Stop the scheduler thread and wait for completion.
        
        Cancels any pending refresh requests and waits for the current
        refresh operation to complete (if any), with a timeout.
        """
        if self._thread is None:
            return
        
        # Signal stop
        self._stop_event.set()
        self._wake_event.set()
        
        # Cancel any pending requests in the queue
        with self._lock:
            while self._queue:
                _, future = self._queue.popleft()
                if not future.done():
                    future.set_result("cancelled-on-shutdown")
        
        # Wait for thread to finish (the thread will finish after current refresh completes, if any)
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
            
            # Limit queue size to prevent memory buildup
            # If queue is too large, skip this request (it will be picked up in next update)
            max_queue_size = 10
            if len(self._queue) >= max_queue_size and not full:
                # Queue is full, skip this request
                future.set_result("skipped-queue-full")
                return future
            
            self._queue.append((region, future))
        
        self._wake_event.set()
        return future

    def _run(self) -> None:
        """Main scheduler loop."""
        print("Refresh scheduler thread started")
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
            
            if len(batch) > 50:
                print(f"WARNING: Processing large batch of {len(batch)} refresh requests - queue may be backing up")
            else:
                print(f"Processing batch of {len(batch)} refresh requests...")
            
            # Check if we need a full refresh
            # Force full refresh more frequently to prevent ghosting from fast-moving content
            time_since_full = time.time() - self._last_full_refresh
            needs_full = (
                any(region is None for region, _ in batch) or
                self._partial_refresh_count >= self._max_partial_refreshes or
                time_since_full > 300  # Force full every 5 minutes to prevent ghosting
            )
            
            # If we're doing partial refreshes very frequently (rapid updates),
            # force a full refresh more often to prevent ghosting
            current_time = time.time()
            time_since_last_partial = current_time - self._last_partial_refresh_time
            if not needs_full and self._partial_refresh_count >= 2:
                # If we've done 2+ partial refreshes and they're happening rapidly (< 0.5s apart),
                # force a full refresh to prevent ghosting from accumulating
                if time_since_last_partial < 0.5 and time_since_full < 1.0:
                    needs_full = True
            
            if needs_full:
                self._execute_full_refresh(batch)
            else:
                self._execute_partial_refreshes(batch)

    def _execute_full_refresh(self, batch: List[tuple[Optional[Region], Future]]) -> None:
        """Execute a full screen refresh."""
        try:
            image = self._framebuffer.snapshot()
            print("Executing full refresh...")
            self._driver.full_refresh(image)
            print("Full refresh completed, flushing framebuffer...")
            self._framebuffer.flush_all()
            self._partial_refresh_count = 0
            self._last_full_refresh = time.time()
            self._last_partial_refresh_time = 0.0
            
            # Complete all futures
            for _, future in batch:
                if not future.done():
                    future.set_result("full")
            print("Full refresh futures completed")
        except Exception as e:
            print(f"ERROR in full refresh: {e}")
            import traceback
            traceback.print_exc()
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
            # Check if we should stop before processing more regions
            if self._stop_event.is_set():
                # Mark remaining futures as cancelled
                for _, future in batch:
                    if not future.done():
                        future.set_result("cancelled-on-shutdown")
                return
            
            # Expand to controller alignment (optimized width, full-height rows)
            expanded = expand_to_controller_alignment(
                region,
                self._driver.width,
                self._driver.height
            )
            
            # Get image for the expanded region
            # With Waveshare driver, we can do true partial-width refreshes,
            # so we only refresh the necessary region (aligned to byte boundaries)
            image = self._framebuffer.snapshot_region(expanded)
            
            try:
                # Use x/y coordinates for partial refresh (Waveshare driver supports this)
                self._driver.partial_refresh(
                    expanded.x1,
                    expanded.y1,
                    expanded.x2,
                    expanded.y2,
                    image
                )
                
                # Mark the expanded region as flushed
                # This ensures the flushed buffer matches what's actually on the display
                self._framebuffer.flush_region(expanded)
                self._partial_refresh_count += 1
                self._last_partial_refresh_time = time.time()
                
                # Small delay between partial refreshes (skip if shutting down)
                if not self._stop_event.is_set():
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

