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
        if self._thread is not None:
            self._thread.join(timeout=5.0)
    
    def submit(self, full: bool = False, immediate: bool = False) -> Future:
        """Submit a refresh request.
        
        Args:
            full: If True, force a full refresh instead of partial refresh.
            immediate: If True, wake scheduler immediately to process without batching delay.
        """
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
                immediate_mode = False
                
                # Check if we should process immediately (for urgent updates like menu navigation)
                if self._wake_event.is_set():
                    self._wake_event.clear()
                    immediate_mode = True
                    # In immediate mode, process only the first item without batching
                    try:
                        item = self._queue.get_nowait()
                        batch.append(item)
                        # Process immediately without collecting more items
                        if batch:
                            self._process_batch(batch)
                        continue
                    except queue.Empty:
                        # No items yet, but wake event was set - continue to normal batching
                        pass
                
                # Normal batching mode - collect requests with timeout
                while len(batch) < 10:
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
        """Process a batch of refresh requests."""
        full_refresh = any(full for full, _ in batch)
        #print(f"Scheduler._process_batch(): full_refresh={full_refresh}, partial_refresh_count={self._partial_refresh_count}")
        if full_refresh or self._partial_refresh_count >= self._max_partial_refreshes:
            self._execute_full_refresh(batch)
        else:
            self._execute_partial_refresh(batch)
    
    def _execute_full_refresh(self, batch: list) -> None:
        """Execute a full screen refresh."""
        #print(f"Scheduler._execute_full_refresh(): Entering")
        try:
            # Only re-initialize if we're transitioning from partial mode to full mode
            # This ensures clean transition from partial refresh mode back to full refresh mode
            # If we're already in full mode, we don't need to re-initialize
            if self._in_partial_mode:
                self._epd.init()
                self._in_partial_mode = False
            
            # Get full-screen snapshot with rotation
            full_image = self._framebuffer.snapshot(rotation=epdconfig.ROTATION)
            
            buf = self._epd.getbuffer(full_image)
            self._epd.display(buf)
            self._framebuffer.flush_all()
            self._partial_refresh_count = 0
        except Exception as e:
            #print(f"ERROR in full refresh: {e}")
            import traceback
            traceback.print_exc()
        
        for _, future in batch:
            if not future.done():
                future.set_result("full")
    
    def _execute_partial_refresh(self, batch: list) -> None:
        """Execute partial refresh using Waveshare DisplayPartial."""
        dirty_regions = self._framebuffer.compute_dirty_regions()
        
        #print(f"Scheduler._execute_partial_refresh(): Found {len(dirty_regions)} dirty regions")
        
        if not dirty_regions:
            #print("Scheduler._execute_partial_refresh(): No dirty regions, returning no-op")
            for _, future in batch:
                if not future.done():
                    future.set_result("no-op")
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
            if not self._in_partial_mode:
                # We're transitioning from full mode to partial mode
                # Reset and clear to establish known state (matches sample code pattern exactly)
                self._epd.init()
                self._epd.Clear()
            
            # Get new (current) snapshot with rotation
            image = self._framebuffer.snapshot(rotation=epdconfig.ROTATION)
            
            # Get buffer from image
            buf = self._epd.getbuffer(image)
            
            self._epd.DisplayPartial(buf)
            
            # Flush entire framebuffer since DisplayPartial refreshes full screen
            self._framebuffer.flush_all()
            
            self._partial_refresh_count += 1
            self._in_partial_mode = True
        except Exception as e:
            log.error(f"ERROR in partial refresh: {e}")
            import traceback
            traceback.print_exc()
        
        for _, future in batch:
            if not future.done():
                future.set_result("partial")
