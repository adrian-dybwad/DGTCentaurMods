"""
Main display manager coordinating widgets and refresh scheduling.
"""

import time
from typing import List
from concurrent.futures import Future
from PIL import Image
from .waveshare.epd2in9d import EPD
from .framebuffer import FrameBuffer
from .scheduler import Scheduler
from .widget import Widget
from .waveshare import epdconfig
from ..status_bar import StatusBarWidget

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
        log.warning(f"Manager.__init__() completed - Manager id: {id(self)}, EPD id: {id(self._epd)}")
    
    def initialize(self) -> Future:
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
            #self._epd.Clear()
            self._framebuffer.flush_all()
            
            self._initialized = True
            return self.clear_widgets()

        except Exception as e:
            raise RuntimeError(f"Failed to initialize display: {e}") from e

        return None
    
    def add_widget(self, widget: Widget) -> None:
        """Add a widget to the display.
        
        The widget should call request_update() when it's ready to be displayed.
        """
        # Check for overlaps
        new_region = widget.get_region()
        for existing in self._widgets:
            if new_region.intersects(existing.get_region()):
                import warnings
                warnings.warn(f"Widget at {new_region} overlaps with widget at {existing.get_region()}")
        
        # Pass scheduler and update callback to widget so it can trigger updates
        widget.set_scheduler(self._scheduler)
        widget.set_update_callback(self.update)
        
        self._widgets.append(widget)

        return self.update(full=False)
    
    def remove_widget(self, widget: Widget) -> Future:
        """Remove a widget from the display.
        
        Args:
            widget: The widget to remove
            
        Returns:
            Future that completes when the display is updated, or None if widget not found
        """
        if widget in self._widgets:
            try:
                widget.stop()
            except Exception as e:
                log.debug(f"Error stopping widget {widget.__class__.__name__} during remove: {e}")
            
            self._widgets.remove(widget)
            log.debug(f"Manager.remove_widget() removed {widget.__class__.__name__}")
            return self.update(full=False)
        else:
            log.debug(f"Manager.remove_widget() widget {widget.__class__.__name__} not found")
            return None
    
    def clear_widgets(self, addStatusBar: bool = True) -> Future:
        """Clear all widgets from the display."""
        log.debug(f"Manager.clear_widgets() called, clearing {len(self._widgets)} widgets")
        # Stop all existing widgets before clearing to prevent background threads from continuing
        for widget in self._widgets:
            try:
                widget.stop()
            except Exception as e:
                log.debug(f"Error stopping widget {widget.__class__.__name__} during clear: {e}")
        
        self._widgets.clear()
        # Create and add status bar widget
        if addStatusBar:
            status_bar_widget = StatusBarWidget(0, 0)
            return self.add_widget(status_bar_widget)
            # if future:
            #     try:
            #         future.result(timeout=10.0)
            #         log.debug(">>> _get_display_manager() status bar widget update completed, display is now in partial mode")
            #     except Exception as e:
            #         log.error(f">>> _get_display_manager() status bar widget update failed: {e}")

        return None
    
    def update(self, full: bool = False) -> Future:
        """Update the display with current widget states.
        
        Args:
            full: If True, force a full refresh instead of partial refresh.
        
        Returns:
            Future: A Future that completes when the display refresh finishes.
        """
        if full:
            log.warning(f"Manager.update() called with full=True (will cause flashing refresh)")
        
        if not self._initialized or self._shutting_down:
            from concurrent.futures import Future
            future = Future()
            future.set_result("not-initialized")
            return future
        
        # Get canvas and clear it to white - start fresh for each update
        # The e-paper driver handles its own state, so we just create the complete image
        canvas = self._framebuffer.get_canvas()
        from PIL import ImageDraw
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, self._epd.width, self._epd.height), fill=255)  # Fill with white
        
        # Separate static and moving widgets, skipping invisible widgets
        static_widgets = []
        moving_widgets = []
        
        for widget in self._widgets:
            # Skip invisible widgets entirely
            if not widget.visible:
                continue
            
            if hasattr(widget, 'get_previous_region'):
                # Moving widget (like ball)
                prev_region = widget.get_previous_region()
                if prev_region.x1 != widget.x or prev_region.y1 != widget.y:
                    moving_widgets.append(widget)
                else:
                    static_widgets.append(widget)
            else:
                static_widgets.append(widget)
        
        # Render static widgets
        for widget in static_widgets:
            widget_image = widget.render()
            canvas.paste(widget_image, (widget.x, widget.y))
        
        # Render moving widgets last (on top)
        for widget in moving_widgets:
            widget_image = widget.render()
            mask = widget.get_mask()
            if mask:
                canvas.paste(widget_image, (widget.x, widget.y), mask)
            else:
                canvas.paste(widget_image, (widget.x, widget.y))
        
        # CRITICAL: Capture snapshot of framebuffer state at this exact moment
        # This ensures each update request carries its own image state, so rapid
        # updates display all intermediate states, not just the final one
        snapshot = self._framebuffer.snapshot(rotation=epdconfig.ROTATION)
        
        # Submit refresh with the captured snapshot and return Future
        return self._scheduler.submit(full=full, image=snapshot)
    
    def shutdown(self) -> None:
        """Shutdown the display."""
        if self._shutting_down:
            return
        
        self._shutting_down = True
        
        try:
            # Stop all widgets to allow cleanup of background threads and resources
            for widget in self._widgets:
                try:
                    widget.stop()
                except Exception as e:
                    log.debug(f"Error stopping widget {widget.__class__.__name__}: {e}")
            
            self._scheduler.stop()
            
            # Clear display to white before sleeping to leave it in a known state
            # try:
            #     self._epd.Clear()
            # except Exception:
            #     # If Clear() fails, try using display() with white image
            #     try:
            #         white_image = Image.new('1', (self._epd.width, self._epd.height), 255)
            #         white_buf = self._epd.getbuffer(white_image)
            #         self._epd.display(white_buf)
            #     except Exception:
            #         pass
            
            self._epd.sleep()
        except Exception as e:
            log.error(f"Error during shutdown: {e}")
