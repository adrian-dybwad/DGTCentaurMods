"""
Refresh scheduler that uses Waveshare DisplayPartial directly.
"""

import threading
import queue
import time
from typing import Optional
from concurrent.futures import Future
from PIL import Image
from .framebuffer import FrameBuffer
from .waveshare.epd2in9d import EPD
from .waveshare import epdconfig

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

class Scheduler:
    """Background thread that schedules display refreshes using Waveshare DisplayPartial.
    
    Args:
        framebuffer: The FrameBuffer to read display state from
        epd: The EPD hardware driver
        on_display_updated: Optional callback invoked with the displayed image (PIL Image)
                            after each successful display update. Used for web dashboard mirroring.
    """
    
    # Maximum queue size - when full, oldest items are dropped to make room for new ones
    QUEUE_MAX_SIZE = 5
    
    def __init__(self, framebuffer: FrameBuffer, epd: EPD, on_display_updated=None):
        self._framebuffer = framebuffer
        self._epd = epd
        self._queue = queue.Queue(maxsize=self.QUEUE_MAX_SIZE)
        self._queue_lock = threading.Lock()  # Protects queue operations during eviction
        self._thread = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()  # Event to wake scheduler for immediate processing
        self._max_partial_refreshes = 200
        self._partial_refresh_count = 0
        self._in_partial_mode = False  # Track if display is in partial refresh mode
        self._on_display_updated = on_display_updated  # Callback after display update
    
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
        self.clear_pending()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
    
    def clear_pending(self) -> None:
        """Clear all pending refresh requests from the queue.
        
        Marks all pending futures as cancelled. Use when transitioning between
        display states to prevent stale updates from rendering.
        """
        with self._queue_lock:
            while not self._queue.empty():
                try:
                    item = self._queue.get_nowait()
                    _, future, _ = item if len(item) == 3 else (item[0], item[1], None)
                    if not future.done():
                        future.set_result("cleared")
                except queue.Empty:
                    break
        log.debug("Scheduler.clear_pending(): Cleared pending refresh requests")
    
    def reset_partial_mode(self) -> None:
        """Reset partial mode flag so next update triggers display re-initialization.
        
        When transitioning between screens (e.g., splash to game), this forces the
        scheduler to re-initialize the display in partial mode on the next update.
        The init() and Clear() sequence clears any ghosting from previous content
        without the jarring full refresh flash.
        
        This is preferred over a full refresh when transitioning between screens
        that both use partial mode updates.
        """
        if self._in_partial_mode:
            log.debug("Scheduler.reset_partial_mode(): Resetting partial mode for display re-initialization")
            self._in_partial_mode = False
    
    def submit_deferred(self, callback) -> None:
        """Schedule a callback to run on the scheduler thread.
        
        Used to defer operations that would cause recursion if executed immediately.
        The callback will run on the next scheduler iteration.
        
        Args:
            callback: A callable to execute on the scheduler thread.
        """
        # Use a simple threading.Timer with 0 delay to defer to next event loop tick
        timer = threading.Timer(0.001, callback)
        timer.daemon = True
        timer.start()
    
    def submit(self, full: bool = False, immediate: bool = False, image: Optional[Image.Image] = None) -> Future:
        """Submit a refresh request.
        
        If the queue is full, the oldest item is dropped to make room for the new one.
        This ensures the display always shows the latest state.
        
        Args:
            full: If True, force a full refresh instead of partial refresh.
            immediate: If True, wake scheduler immediately to process without batching delay.
            image: Optional pre-captured image snapshot. If provided, this exact image will be
                   displayed. If None, scheduler will take snapshot from framebuffer when processing.
        """
        if full:
            log.warning(f"Scheduler.submit() called with full=True (will cause flashing refresh)")
        
        future = Future()
        with self._queue_lock:
            # If queue is full, drop oldest item to make room
            if self._queue.full():
                try:
                    old_item = self._queue.get_nowait()
                    _, old_future, _ = old_item if len(old_item) == 3 else (old_item[0], old_item[1], None)
                    if not old_future.done():
                        old_future.set_result("evicted")
                    log.warning("Scheduler.submit(): Queue full, evicted oldest item to make room for new update")
                except queue.Empty:
                    pass  # Queue was emptied by another thread, that's fine
            
            try:
                self._queue.put_nowait((full, future, image))
                if immediate:
                    # Wake scheduler thread immediately for urgent updates (e.g., menu arrow)
                    self._wake_event.set()
            except queue.Full:
                # Should not happen after eviction, but handle gracefully
                log.warning("Scheduler.submit(): Queue still full after eviction attempt")
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
        Each item carries its own image snapshot captured at render time.
        """
        # Process each item separately to ensure all updates are displayed
        for item in batch:
            if self._stop_event.is_set():
                full, future, _ = item if len(item) == 3 else (item[0], item[1], None)
                if not future.done():
                    future.set_result("shutdown")
                continue
            
            # Unpack item (handle both old format and new format with image)
            if len(item) == 3:
                full, future, image = item
            else:
                full, future = item
                image = None
            
            # Full refresh when explicitly requested or when partial count exceeds max
            full_refresh = full or self._partial_refresh_count >= self._max_partial_refreshes
            if full_refresh:
                self._execute_full_refresh_single(full, future, image)
            else:
                self._execute_partial_refresh_single(full, future, image)
    
    def _execute_full_refresh_single(self, full: bool, future: Future, image: Optional[Image.Image]) -> None:
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
            
            # Use provided image if available, otherwise take snapshot from framebuffer
            if image is not None:
                full_image = image
            else:
                full_image = self._framebuffer.snapshot(rotation=epdconfig.ROTATION)
            
            buf = self._epd.getbuffer(full_image)
            log.debug(f"Scheduler: Sending FULL refresh to display")
            self._epd.display(buf)
            self._partial_refresh_count = 0
            
            # Invoke callback after successful display update
            if self._on_display_updated:
                try:
                    self._on_display_updated(full_image)
                except Exception as cb_e:
                    log.debug(f"on_display_updated callback failed: {cb_e}")
        except Exception as e:
            # Don't log errors during shutdown (SPI may be closed)
            # Also suppress GPIO-related errors that occur during shutdown race conditions
            error_msg = str(e).lower()
            is_shutdown_error = 'closed' in error_msg or 'uninitialized' in error_msg or 'gpio' in error_msg
            if not self._stop_event.is_set() and not is_shutdown_error:
                log.error(f"ERROR in full refresh: {e}")
                import traceback
                traceback.print_exc()
        
        if not future.done():
            future.set_result("full")
    
    def _execute_partial_refresh_single(self, full: bool, future: Future, image: Optional[Image.Image]) -> None:
        """Execute partial refresh for a single request."""
        # Check if shutdown was requested before using hardware
        if self._stop_event.is_set():
            if not future.done():
                future.set_result("shutdown")
            return
        
        try:
            # CRITICAL: Before first partial refresh after full refresh, we must reset and clear
            # the display to establish a known state, exactly like the sample code does.
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
                self._in_partial_mode = True
                log.debug(f"Scheduler._execute_partial_refresh_single(): Transition complete, _in_partial_mode is now True")
            
            # Use provided image or take snapshot from framebuffer
            if image is not None:
                display_image = image
            else:
                display_image = self._framebuffer.snapshot(rotation=epdconfig.ROTATION)
            
            # Final check before continuing (SPI might be closed during shutdown)
            if self._stop_event.is_set():
                if not future.done():
                    future.set_result("shutdown")
                return
            
            # Get buffer from image and display
            buf = self._epd.getbuffer(display_image)
            log.debug(f"Scheduler: Sending PARTIAL refresh to display (count={self._partial_refresh_count + 1})")
            self._epd.DisplayPartial(buf)
            
            self._partial_refresh_count += 1
            
            # Invoke callback after successful display update
            if self._on_display_updated:
                try:
                    self._on_display_updated(display_image)
                except Exception as cb_e:
                    log.debug(f"on_display_updated callback failed: {cb_e}")
        except Exception as e:
            # Don't log errors during shutdown (SPI may be closed)
            # Also suppress GPIO-related errors that occur during shutdown race conditions
            error_msg = str(e).lower()
            is_shutdown_error = 'closed' in error_msg or 'uninitialized' in error_msg
            if not self._stop_event.is_set() and not is_shutdown_error:
                log.error(f"ERROR in partial refresh: {e}")
                import traceback
                traceback.print_exc()
        
        if not future.done():
            future.set_result("partial")
