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
        self._shutting_down = False

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
            
            try:
                print("Resetting display...")
                self._driver.reset()
                print("Initializing display hardware...")
                self._driver.init()
                print("Display hardware initialized successfully")
            except Exception as e:
                print(f"ERROR: Failed to initialize display: {e}")
                raise
            
            self._scheduler = RefreshScheduler(self._driver, self._framebuffer)
            self._scheduler.start()
            
            # Give scheduler thread a moment to start
            import time
            time.sleep(0.1)
            
            # Clear display on init
            print("Clearing display with initial full refresh...")
            self._framebuffer.clear()
            future = self._scheduler.submit(full=True)
            try:
                result = future.result(timeout=10.0)  # Full refresh can take 1.5-2 seconds
                print(f"Initial refresh completed: {result}")
            except Exception as e:
                print(f"WARNING: Initial refresh failed or timed out: {e}")
                # Continue anyway - display might still work
            
            self._initialized = True

    def shutdown(self) -> None:
        """Shutdown the display and scheduler."""
        with self._lock:
            if not self._initialized or self._shutting_down:
                return
            
            self._shutting_down = True
            
            # Stop scheduler first to prevent new refresh requests
            # The scheduler will finish any in-progress refresh
            if self._scheduler:
                self._scheduler.stop()
            
            # Put display to sleep and shutdown
            if self._driver:
                self._driver.sleep()
                self._driver.shutdown()
            
            self._initialized = False
            self._shutting_down = False

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
        if self._shutting_down:
            return
        
        if not self._initialized:
            self.init()
        
        with self._lock:
            # Render all widgets to framebuffer
            # We render all widgets to ensure correct compositing, even if unchanged
            canvas = self._framebuffer.get_canvas()
            
            # Separate static widgets from moving widgets (like ball)
            static_widgets = []
            moving_widgets = []
            moved_regions = []
            
            for widget in self._widgets:
                # Check if widget has moved (has get_previous_region method)
                if hasattr(widget, 'get_previous_region'):
                    moving_widgets.append(widget)
                    prev_region = widget.get_previous_region()
                    curr_region = widget.get_region()
                    # If position changed, mark old region for clearing
                    if prev_region != curr_region:
                        moved_regions.append(Region(
                            prev_region[0],
                            prev_region[1],
                            prev_region[2],
                            prev_region[3]
                        ))
                else:
                    static_widgets.append(widget)
            
            # Step 1: Render all static widgets first
            for widget in static_widgets:
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
            
            # Step 2: Clear old positions of moving widgets
            for moved_region in moved_regions:
                # First, re-render static widgets that overlap with the old position
                has_static_overlap = False
                for widget in static_widgets:
                    widget_region = widget.get_region()
                    if moved_region.intersects(Region(*widget_region)):
                        # This widget overlaps the old position, re-render it to clear the old ball
                        has_static_overlap = True
                        widget_image = widget.get_image()
                        if widget_image.mode != "1":
                            widget_image = widget_image.convert("1")
                        canvas.paste(widget_image, (widget.x, widget.y))
                
                # If no static widgets overlap the old position, explicitly clear it with white
                if not has_static_overlap:
                    from PIL import ImageDraw
                    draw = ImageDraw.Draw(canvas)
                    # Clear the old position with white
                    draw.rectangle(
                        moved_region.to_box(),
                        fill=255,
                        outline=255
                    )
            
            # Step 3: Render moving widgets last (so they appear on top)
            for widget in moving_widgets:
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
                
                # For widgets with a mask (like ball), use mask for compositing
                # This allows the widget to appear on top without overwriting background
                if hasattr(widget, 'get_mask'):
                    mask = widget.get_mask()
                    if mask.size != (widget.width, widget.height):
                        mask = mask.resize(
                            (widget.width, widget.height),
                            Image.Resampling.NEAREST
                        )
                    # Paste with mask - in mode "1", mask determines which pixels are updated
                    # White (255) in mask means paste, black (0) means keep existing
                    canvas.paste(widget_image, (widget.x, widget.y), mask)
                else:
                    # Paste widget onto canvas (last, so it's on top)
                    canvas.paste(widget_image, (widget.x, widget.y))
            
            # Compute dirty regions
            if force_full:
                dirty_region = Region.full(self.width, self.height)
                self._scheduler.submit(dirty_region, full=True)
            else:
                dirty_regions = self._framebuffer.compute_dirty_regions()
                # Add moved regions to ensure old positions are refreshed
                dirty_regions.extend(moved_regions)
                if dirty_regions:
                    # Merge regions before submitting to reduce queue size
                    from .regions import merge_regions
                    merged_regions = merge_regions(dirty_regions)
                    
                    # Submit refresh requests for each merged region (fewer requests = less queue buildup)
                    for region in merged_regions:
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

