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


class Scheduler:
    """Background thread that schedules display refreshes using Waveshare DisplayPartial."""
    
    def __init__(self, framebuffer: FrameBuffer, epd: EPD):
        self._framebuffer = framebuffer
        self._epd = epd
        self._queue = queue.Queue(maxsize=10)
        self._thread = None
        self._stop_event = threading.Event()
        self._max_partial_refreshes = 50
        self._partial_refresh_count = 0
    
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
    
    def submit(self, full: bool = False) -> Future:
        """Submit a refresh request."""
        future = Future()
        try:
            self._queue.put_nowait((full, future))
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
                    try:
                        item = self._queue.get(timeout=timeout)
                        batch.append(item)
                        timeout = 0.0
                    except queue.Empty:
                        break
                
                if batch:
                    self._process_batch(batch)
                    
            except Exception as e:
                print(f"ERROR in refresh scheduler: {e}")
                import traceback
                traceback.print_exc()
    
    def _process_batch(self, batch: list) -> None:
        """Process a batch of refresh requests."""
        full_refresh = any(full for full, _ in batch)
        
        if full_refresh or self._partial_refresh_count >= self._max_partial_refreshes:
            self._execute_full_refresh(batch)
        else:
            self._execute_partial_refresh(batch)
    
    def _execute_full_refresh(self, batch: list) -> None:
        """Execute a full screen refresh."""
        try:
            # Re-initialize to ensure we're in full refresh mode (not partial mode)
            # This ensures clean transition from partial refresh mode back to full refresh mode
            self._epd.init()
            
            # Get full-screen snapshot and rotate 180° for hardware orientation
            full_image = self._framebuffer.snapshot()
            full_image = full_image.transpose(Image.ROTATE_180)
            
            buf = self._epd.getbuffer(full_image)
            self._epd.display(buf)
            self._framebuffer.flush_all()
            self._partial_refresh_count = 0
        except Exception as e:
            print(f"ERROR in full refresh: {e}")
            import traceback
            traceback.print_exc()
        
        for _, future in batch:
            if not future.done():
                future.set_result("full")
    
    def _execute_partial_refresh(self, batch: list) -> None:
        """Execute partial refresh using Waveshare DisplayPartial."""
        dirty_regions = self._framebuffer.compute_dirty_regions()
        
        print(f"Scheduler._execute_partial_refresh(): Found {len(dirty_regions)} dirty regions")
        
        if not dirty_regions:
            print("Scheduler._execute_partial_refresh(): No dirty regions, returning no-op")
            for _, future in batch:
                if not future.done():
                    future.set_result("no-op")
            return
        
        try:
            # CRITICAL FIX: DisplayPartial() uses different buffer mapping than display()
            # display() sends: 0x10=zeros, 0x13=image
            # DisplayPartial() sends: 0x10=image, 0x13=~image
            # 
            # The display hardware interprets these differently. After a full refresh with display(),
            # the display expects the image in 0x13. But DisplayPartial() puts it in 0x10.
            # 
            # The solution: We need to ensure the display is in partial mode state before
            # using DisplayPartial(). Since DisplayPartial() calls SetPartReg() which configures
            # partial mode, we should be fine. But the buffer format needs to match.
            #
            # Actually, looking at the sample code, they pass the buffer directly without inversion.
            # The issue might be that we need to ensure we're starting from a known state.
            # Let's try inverting the buffer so that when DisplayPartial() processes it,
            # we get the same visual result as display().
            
            # Get full-screen snapshot and rotate 180° for hardware orientation
            full_image = self._framebuffer.snapshot()
            full_image = full_image.transpose(Image.ROTATE_180)
            
            buf = self._epd.getbuffer(full_image)
            
            # Invert buffer: DisplayPartial sends image to 0x10 and ~image to 0x13
            # But display() sends image to 0x13. To get same result, we need to invert
            # so that DisplayPartial's 0x10 buffer matches what display() put in 0x13
            inverted_buf = [(~b) & 0xFF for b in buf]
            
            # Use DisplayPartial - it handles the full screen buffer
            # DisplayPartial refreshes the entire screen, so flush entire framebuffer
            # Note: DisplayPartial() calls SetPartReg() which puts display in partial mode
            self._epd.DisplayPartial(inverted_buf)
            
            # Flush entire framebuffer since DisplayPartial refreshes full screen
            self._framebuffer.flush_all()
            
            self._partial_refresh_count += 1
        except Exception as e:
            print(f"ERROR in partial refresh: {e}")
            import traceback
            traceback.print_exc()
        
        for _, future in batch:
            if not future.done():
                future.set_result("partial")
