"""
Main display manager coordinating widgets and refresh scheduling.
"""

import time
from typing import List
from PIL import Image
from .waveshare.epd2in9d import EPD
from .framebuffer import FrameBuffer
from .scheduler import Scheduler
from .widget import Widget
from .regions import Region, merge_regions

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class Manager:
    """Main coordinator for the ePaper framework."""
    
    def __init__(self):
        self._epd = EPD()
        self._framebuffer = FrameBuffer(self._epd.width, self._epd.height)
        self._scheduler = Scheduler(self._framebuffer, self._epd)
        self._widgets: List[Widget] = []
        self._initialized = False
        self._shutting_down = False
        self._first_update = True  # Track if this is the first update after init
    
    def init(self) -> None:
        """Initialize the display."""
        if self._initialized:
            return
        
        try:
            result = self._epd.init()
            if result != 0:
                raise RuntimeError("Failed to initialize e-Paper display")
            
            self._scheduler.start()
            time.sleep(0.1)
            
            # Initial full refresh
            self._epd.Clear()
            self._framebuffer.flush_all()
            
            self._initialized = True
        except Exception as e:
            raise RuntimeError(f"Failed to initialize display: {e}") from e
    
    def add_widget(self, widget: Widget) -> None:
        """Add a widget to the display."""
        # Check for overlaps
        new_region = widget.get_region()
        for existing in self._widgets:
            if new_region.intersects(existing.get_region()):
                import warnings
                warnings.warn(f"Widget at {new_region} overlaps with widget at {existing.get_region()}")
        
        self._widgets.append(widget)
    
    def update(self, full: bool = False):
        """Update the display with current widget states.
        
        Args:
            full: If True, force a full refresh instead of partial refresh.
        
        Returns:
            Future: A Future that completes when the display refresh finishes.
        """
        if not self._initialized or self._shutting_down:
            from concurrent.futures import Future
            future = Future()
            future.set_result("not-initialized")
            return future
        
        # Reset canvas to last flushed state
        canvas = self._framebuffer.get_canvas()
        canvas.paste(self._framebuffer._flushed)
        
        # Separate static and moving widgets
        static_widgets = []
        moving_widgets = []
        moved_regions = []
        
        for widget in self._widgets:
            if hasattr(widget, 'get_previous_region'):
                # Moving widget (like ball)
                prev_region = widget.get_previous_region()
                if prev_region.x1 != widget.x or prev_region.y1 != widget.y:
                    moved_regions.append(prev_region)
                    moving_widgets.append(widget)
                else:
                    static_widgets.append(widget)
            else:
                static_widgets.append(widget)
        
        # Clear moved regions by re-rendering overlapping static widgets
        for moved_region in moved_regions:
            cleared = False
            for static in static_widgets:
                if moved_region.intersects(static.get_region()):
                    static_image = static.render()
                    canvas.paste(static_image, (static.x, static.y))
                    cleared = True
            
            # If no static widget overlaps, clear with white
            if not cleared:
                from PIL import ImageDraw
                draw = ImageDraw.Draw(canvas)
                draw.rectangle(
                    [moved_region.x1, moved_region.y1, moved_region.x2, moved_region.y2],
                    fill=255
                )
        
        # Render static widgets
        for widget in static_widgets:
            widget_image = widget.render()
            widget_name = widget.__class__.__name__
            log.info(f"Manager.update(): Pasting {widget_name} at ({widget.x},{widget.y}), size={widget.width}x{widget.height}")
            
            # Get canvas state before pasting
            before_crop = canvas.crop((widget.x, widget.y, widget.x + widget.width, widget.y + widget.height))
            before_bytes = before_crop.tobytes()
            widget_bytes = widget_image.tobytes()
            log.info(f"Manager.update(): Before paste - canvas region hash={hash(before_bytes)}, widget hash={hash(widget_bytes)}")
            
            canvas.paste(widget_image, (widget.x, widget.y))
            
            # Get canvas state after pasting
            after_crop = canvas.crop((widget.x, widget.y, widget.x + widget.width, widget.y + widget.height))
            after_bytes = after_crop.tobytes()
            log.info(f"Manager.update(): After paste - canvas region hash={hash(after_bytes)}, changed={before_bytes != after_bytes}")
        
        # Render moving widgets last (on top)
        for widget in moving_widgets:
            widget_image = widget.render()
            mask = widget.get_mask()
            if mask:
                canvas.paste(widget_image, (widget.x, widget.y), mask)
            else:
                canvas.paste(widget_image, (widget.x, widget.y))
        
        # Check for dirty regions before submitting
        dirty_regions = self._framebuffer.compute_dirty_regions()
        log.info(f"Manager.update(): Found {len(dirty_regions)} dirty regions before submitting refresh")
        
        # First update after init must be a full refresh to establish baseline
        # Partial refresh mode requires the display to be in a known state
        if self._first_update:
            #full = True
            self._first_update = False
        
        # Submit refresh and return Future for caller to wait on
        return self._scheduler.submit(full=full)
    
    def shutdown(self) -> None:
        """Shutdown the display."""
        if self._shutting_down:
            return
        
        self._shutting_down = True
        
        try:
            self._scheduler.stop()
            
            # Clear display to white before sleeping to leave it in a known state
            try:
                self._epd.Clear()
            except Exception:
                # If Clear() fails, try using display() with white image
                try:
                    white_image = Image.new('1', (self._epd.width, self._epd.height), 255)
                    white_buf = self._epd.getbuffer(white_image)
                    self._epd.display(white_buf)
                except Exception:
                    pass
            
            self._epd.sleep()
        except Exception as e:
            print(f"Error during shutdown: {e}")
