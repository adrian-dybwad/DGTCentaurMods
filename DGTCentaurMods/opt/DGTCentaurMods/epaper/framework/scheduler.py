"""
Refresh scheduler that uses Waveshare DisplayPartial directly.
"""

import threading
import queue
import time
from typing import Optional
from concurrent.futures import Future
from PIL import Image
from .regions import Region, merge_regions, expand_to_byte_alignment
from .framebuffer import FrameBuffer
from .waveshare.epd2in9d import EPD
from .waveshare import epdconfig

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

class Scheduler:
    """Background thread that schedules display refreshes using Waveshare DisplayPartial."""
    
    def __init__(self, framebuffer: FrameBuffer, epd: EPD):
        self._framebuffer = framebuffer
        self._epd = epd
        self._queue = queue.Queue(maxsize=10)
        self._thread = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()  # Event to wake scheduler for immediate processing
        self._max_partial_refreshes = 50
        self._partial_refresh_count = 0
        self._in_partial_mode = False  # Track if display is in partial refresh mode
    
    def start(self) -> None:
        """Start the refresh scheduler thread."""
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
    
    def stop(self) -> None:
        """Stop the refresh scheduler thread."""
        self._stop_event.set()
        # Wake the thread if it's waiting
        self._wake_event.set()
        # Drain the queue to prevent new operations from starting
        while not self._queue.empty():
            try:
                _, future = self._queue.get_nowait()
                if not future.done():
                    future.set_result("shutdown")
            except queue.Empty:
                break
        if self._thread is not None:
            self._thread.join(timeout=5.0)
    
    def submit(self, full: bool = False, immediate: bool = False) -> Future:
        """Submit a refresh request.
        
        Args:
            full: If True, force a full refresh instead of partial refresh.
            immediate: If True, wake scheduler immediately to process without batching delay.
        """
        if full:
            log.warning(f"Scheduler.submit() called with full=True (will cause flashing refresh)")
        
        future = Future()
        try:
            self._queue.put_nowait((full, future))
            if immediate:
                # Wake scheduler thread immediately for urgent updates (e.g., menu arrow)
                self._wake_event.set()
        except queue.Full:
            future.set_result("queue-full")
        return future
    
    def _run(self) -> None:
        """Main scheduler loop."""
        while not self._stop_event.is_set():
            try:
                batch = []
                timeout = 0.1
                
                # Collect batch of requests
                while len(batch) < 10:
                    # Check if we should wake up immediately (for urgent updates like menu navigation)
                    if self._wake_event.is_set():
                        self._wake_event.clear()
                        # Try to get item immediately without waiting
                        try:
                            item = self._queue.get_nowait()
                            batch.append(item)
                            timeout = 0.0
                            continue
                        except queue.Empty:
                            # No items yet, but wake event was set - process what we have
                            break
                    
                    try:
                        item = self._queue.get(timeout=timeout)
                        batch.append(item)
                        timeout = 0.0
                    except queue.Empty:
                        break
                
                if batch:
                    self._process_batch(batch)
                    
            except Exception as e:
                log.error(f"ERROR in refresh scheduler: {e}")
                import traceback
                traceback.print_exc()
    
    def _process_batch(self, batch: list) -> None:
        """Process a batch of refresh requests.
        
        Each item in the batch is processed separately to ensure rapid updates
        (like menu navigation) display all intermediate states, not just the final state.
        """
        # Process each item separately to ensure all updates are displayed
        for full, future in batch:
            if self._stop_event.is_set():
                if not future.done():
                    future.set_result("shutdown")
                continue
            
            full_refresh = full or self._partial_refresh_count >= self._max_partial_refreshes
            if full_refresh:
                if full:
                    log.debug(f"Scheduler._process_batch(): Executing FULL refresh due to explicit request. _in_partial_mode={self._in_partial_mode}")
                else:
                    log.debug(f"Scheduler._process_batch(): Executing FULL refresh due to partial refresh count ({self._partial_refresh_count}) exceeding max ({self._max_partial_refreshes}). _in_partial_mode={self._in_partial_mode}")
                self._execute_full_refresh_single(full, future)
            else:
                log.debug(f"Scheduler._process_batch(): Executing PARTIAL refresh. _in_partial_mode={self._in_partial_mode}, partial_refresh_count={self._partial_refresh_count}")
                self._execute_partial_refresh_single(full, future)
    
    def _execute_full_refresh_single(self, full: bool, future: Future) -> None:
        """Execute a full screen refresh for a single request."""
        # Check if shutdown was requested before using hardware
        if self._stop_event.is_set():
            if not future.done():
                future.set_result("shutdown")
            return
        
        try:
            # Only re-initialize if we're transitioning from partial mode to full mode
            if self._in_partial_mode:
                log.debug(f"Scheduler._execute_full_refresh_single(): Transitioning from PARTIAL to FULL mode")
                self._epd.init()
                self._in_partial_mode = False
            
            # Get full-screen snapshot with rotation
            full_image = self._framebuffer.snapshot(rotation=epdconfig.ROTATION)
            
            buf = self._epd.getbuffer(full_image)
            self._epd.display(buf)
            self._framebuffer.flush_all()
            self._partial_refresh_count = 0
        except Exception as e:
            # Don't log errors during shutdown (SPI may be closed)
            if not self._stop_event.is_set():
                log.error(f"ERROR in full refresh: {e}")
                import traceback
                traceback.print_exc()
        
        if not future.done():
            future.set_result("full")
    
    def _execute_partial_refresh_single(self, full: bool, future: Future) -> None:
        """Execute partial refresh for a single request."""
        # Check if shutdown was requested before using hardware
        if self._stop_event.is_set():
            if not future.done():
                future.set_result("shutdown")
            return
        
        try:
            # CRITICAL: Before first partial refresh after full refresh, we must reset and clear
            # the display to establish a known state, exactly like the sample code does.
            # The sample code (epd_2in9d_test.py lines 79-80) always calls:
            #   epd.init()    # Reset hardware, configure for full mode
            #   epd.Clear()   # Clear to white using display() method
            #   # THEN DisplayPartial() is called
            #
            # This ensures the display hardware is in a known state before switching to partial mode.
            # Without this, the hardware may incorrectly interpret the partial refresh buffers when
            # transitioning from full mode (where image is in 0x13) to partial mode (where image is in 0x10).
            #
            # IMPORTANT: This transition logic must happen BEFORE checking for dirty regions,
            # so that _in_partial_mode is set to True even if there are no dirty regions.
            # Otherwise, subsequent partial refresh requests will incorrectly re-initialize the display.
            if not self._in_partial_mode:
                # Check again before using hardware (might have been shut down while processing)
                if self._stop_event.is_set():
                    if not future.done():
                        future.set_result("shutdown")
                    return
                
                # We're transitioning from full mode to partial mode
                # Reset and clear to establish known state (matches sample code pattern exactly)
                log.debug(f"Scheduler._execute_partial_refresh_single(): Transitioning to partial mode (calling init() and Clear())")
                self._epd.init()
                self._epd.Clear()
                # Mark as in partial mode immediately after transition, even if no dirty regions
                self._in_partial_mode = True
                log.debug(f"Scheduler._execute_partial_refresh_single(): Transition complete, _in_partial_mode is now True")
            
            # Check for dirty regions after transition logic
            dirty_regions = self._framebuffer.compute_dirty_regions()
            
            if not dirty_regions:
                # Even though there are no dirty regions, we've already transitioned to partial mode
                # so mark future as complete
                if not future.done():
                    future.set_result("no-op")
                return
            
            # Final check before continuing (SPI might be closed during shutdown)
            if self._stop_event.is_set():
                if not future.done():
                    future.set_result("shutdown")
                return
            
            # Get new (current) snapshot with rotation - this captures the framebuffer state
            # at the moment this specific update request is processed
            image = self._framebuffer.snapshot(rotation=epdconfig.ROTATION)
            
            # Get buffer from image
            buf = self._epd.getbuffer(image)
            
            self._epd.DisplayPartial(buf)
            
            # Flush entire framebuffer since DisplayPartial refreshes full screen
            self._framebuffer.flush_all()
            
            self._partial_refresh_count += 1
        except Exception as e:
            # Don't log errors during shutdown (SPI may be closed)
            if not self._stop_event.is_set():
                log.error(f"ERROR in partial refresh: {e}")
                import traceback
                traceback.print_exc()
        
        if not future.done():
            future.set_result("partial")
