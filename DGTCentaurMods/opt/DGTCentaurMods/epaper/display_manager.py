"""
Display manager coordinates widgets, framebuffer, and refresh scheduling.
"""

import os
import threading
from typing import List, Optional

from PIL import Image

from .driver import Driver
from .framebuffer import FrameBuffer
from .refresh_scheduler import RefreshScheduler
from .regions import Region
from .widget import Widget


class DisplayManager:
    """
    Main entry point for the ePaper framework.
    
    Manages widgets, coordinates rendering, tracks dirty regions,
    and schedules display refreshes automatically.
    """

    def __init__(self, width: int = 128, height: int = 296) -> None:
        """
        Initialize the display manager.
        
        Args:
            width: Display width in pixels (default 128)
            height: Display height in pixels (default 296)
        """
        self.width = width
        self.height = height
        
        self._framebuffer = FrameBuffer(width, height)
        self._driver: Optional[Driver] = None
        self._scheduler: Optional[RefreshScheduler] = None
        self._widgets: List[Widget] = []
        self._lock = threading.RLock()
        self._initialized = False

    def init(self, use_simulator: bool = False) -> None:
        """
        Initialize the display hardware and start the scheduler.
        
        Args:
            use_simulator: If True, use simulator mode (saves PNGs instead of hardware)
        """
        with self._lock:
            if self._initialized:
                return
            
            # Check for simulator mode via environment variable
            if use_simulator or os.environ.get("EPAPER_SIMULATOR", "").lower() == "true":
                from .simulator_driver import SimulatorDriver
                self._driver = SimulatorDriver()
            else:
                self._driver = Driver()
            
            self._driver.reset()
            self._driver.init()
            
            self._scheduler = RefreshScheduler(self._driver, self._framebuffer)
            self._scheduler.start()
            
            # Clear display on init
            self._framebuffer.clear()
            self._scheduler.submit(full=True).result(timeout=5.0)
            
            self._initialized = True

    def shutdown(self) -> None:
        """Shutdown the display and scheduler."""
        with self._lock:
            if not self._initialized:
                return
            
            # Flush any pending updates
            self.update()
            self._scheduler.submit(full=False).result(timeout=5.0)
            
            if self._scheduler:
                self._scheduler.stop()
            
            if self._driver:
                self._driver.sleep()
                self._driver.shutdown()
            
            self._initialized = False

    def add_widget(self, widget: Widget) -> None:
        """
        Add a widget to the display.
        
        Args:
            widget: Widget instance to add
        """
        with self._lock:
            # Check for overlaps (warning only, not enforced)
            widget_region = widget.get_region()
            for existing in self._widgets:
                existing_region = existing.get_region()
                if self._regions_overlap(widget_region, existing_region):
                    import warnings
                    warnings.warn(
                        f"Widget at {widget_region} overlaps with widget at {existing_region}",
                        UserWarning
                    )
            
            self._widgets.append(widget)

    def remove_widget(self, widget: Widget) -> None:
        """Remove a widget from the display."""
        with self._lock:
            if widget in self._widgets:
                self._widgets.remove(widget)
                # Clear the widget's region
                self._clear_widget_region(widget)

    def _clear_widget_region(self, widget: Widget) -> None:
        """Clear a widget's region on the framebuffer."""
        x, y, x2, y2 = widget.get_region()
        region = Region(x, y, x2, y2)
        canvas = self._framebuffer.get_canvas()
        from PIL import ImageDraw
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(region.to_box(), fill=255, outline=255)

    def _regions_overlap(self, r1: tuple, r2: tuple) -> bool:
        """Check if two regions overlap."""
        x1, y1, x2, y2 = r1
        x3, y3, x4, y4 = r2
        return not (x2 <= x3 or x4 <= x1 or y2 <= y3 or y4 <= y1)

    def update(self, force_full: bool = False) -> None:
        """
        Update the display by rendering all widgets and refreshing changed regions.
        
        Args:
            force_full: If True, force a full screen refresh
        """
        if not self._initialized:
            self.init()
        
        with self._lock:
            # Render all widgets to framebuffer
            # We render all widgets to ensure correct compositing, even if unchanged
            canvas = self._framebuffer.get_canvas()
            
            for widget in self._widgets:
                # Always render to ensure framebuffer is up to date
                widget_image = widget.get_image()
                
                # Ensure widget image matches expected size
                if widget_image.size != (widget.width, widget.height):
                    widget_image = widget_image.resize(
                        (widget.width, widget.height),
                        Image.Resampling.NEAREST
                    )
                
                # Ensure 1-bit mode
                if widget_image.mode != "1":
                    widget_image = widget_image.convert("1")
                
                # Paste widget onto canvas
                canvas.paste(widget_image, (widget.x, widget.y))
            
            # Compute dirty regions
            if force_full:
                dirty_region = Region.full(self.width, self.height)
                self._scheduler.submit(dirty_region, full=True)
            else:
                dirty_regions = self._framebuffer.compute_dirty_regions()
                if dirty_regions:
                    # Submit all dirty regions (scheduler will merge them)
                    for region in dirty_regions:
                        self._scheduler.submit(region, full=False)

    def clear(self) -> None:
        """Clear the entire display."""
        with self._lock:
            self._framebuffer.clear()
            if self._scheduler:
                self._scheduler.submit(full=True).result(timeout=5.0)

    def get_snapshot(self) -> Image.Image:
        """Get a snapshot of the current framebuffer."""
        return self._framebuffer.snapshot()

