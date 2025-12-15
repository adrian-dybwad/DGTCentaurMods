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

import logging
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

class Manager:
    """Main coordinator for the ePaper framework.
    
    Args:
        on_refresh: Optional callback invoked with the display image (PIL Image)
                    after each successful display update. Used for web dashboard mirroring.
    """
    
    def __init__(self, on_refresh=None):
        self._epd = EPD()
        self._framebuffer = FrameBuffer(self._epd.width, self._epd.height)
        self._scheduler = Scheduler(self._framebuffer, self._epd, on_display_updated=on_refresh)
        self._widgets: List[Widget] = []
        self._background = None  # Optional BackgroundWidget for dithered backgrounds
        self._initialized = False
        self._shutting_down = False
        log.debug(f"Manager.__init__() completed - Manager id: {id(self)}, EPD id: {id(self._epd)}")
    
    def initialize(self, background_shade: int = 4) -> Future:
        """Initialize the display.
        
        The status bar is not added by default during initialization.
        The caller is responsible for adding it when appropriate (e.g., when showing a menu).
        This prevents the status bar from briefly appearing before a splash screen is shown.
        
        Args:
            background_shade: Default background shade 0-16 (0=white, 16=black, default=4)
        """
        if self._initialized:
            return
        
        try:
            result = self._epd.init()
            if result != 0:
                raise RuntimeError("Failed to initialize e-Paper display")
            
            self._scheduler.start()
            time.sleep(0.1)
            
            # Set default background for visual depth
            self.set_background(shade=background_shade)
            
            self._initialized = True
            return self.clear_widgets(addStatusBar=False)

        except Exception as e:
            raise RuntimeError(f"Failed to initialize display: {e}") from e

        return None
    
    def add_widget(self, widget: Widget) -> Future:
        """Add a widget to the display.
        
        If the widget has is_modal=True, it takes over the display and all other
        widgets are ignored until this widget is removed.
        
        If adding a modal widget when another modal is already present, the previous
        modal is automatically removed and a warning is logged.
        
        The widget should call request_update() when it's ready to be displayed.
        
        Args:
            widget: The widget to add
            index: Optional position in the widget stack. If None, widget is added
                   at the end (top of z-order). Use 0 to add at bottom.
        """
        # If adding a modal widget, check for and remove any existing modal
        if widget.is_modal:
            for existing in self._widgets:
                if existing.is_modal:
                    log.warning(f"Manager.add_widget() replacing existing modal {existing.__class__.__name__} with {widget.__class__.__name__}")
                    try:
                        existing.stop()
                    except Exception as e:
                        log.debug(f"Error stopping replaced modal widget: {e}")
                    self._widgets.remove(existing)
                    break  # Only one modal should exist
        
        # Pass scheduler and update callback to widget so it can trigger updates
        widget.set_scheduler(self._scheduler)
        widget.set_update_callback(self.update)
        
        self._widgets.append(widget)
        
        if widget.is_modal:
            log.debug(f"Manager.add_widget() added modal widget {widget.__class__.__name__}")

        return self.update(full=False)
    
    def add_widget_at(self, widget: Widget, index: int) -> Future:
        """Add a widget at a specific position in the z-order stack.
        
        Widgets are rendered in order, so index 0 is at the bottom (rendered first,
        may be obscured by others) and higher indices are on top.
        
        Args:
            widget: The widget to add
            index: Position in the stack. Clamped to valid range.
        
        Returns:
            Future that completes when the display is updated
        """
        # If adding a modal widget, check for and remove any existing modal
        if widget.is_modal:
            for existing in self._widgets:
                if existing.is_modal:
                    log.warning(f"Manager.add_widget_at() replacing existing modal {existing.__class__.__name__} with {widget.__class__.__name__}")
                    try:
                        existing.stop()
                    except Exception as e:
                        log.debug(f"Error stopping replaced modal widget: {e}")
                    self._widgets.remove(existing)
                    break
        
        # Pass scheduler and update callback to widget
        widget.set_scheduler(self._scheduler)
        widget.set_update_callback(self.update)
        
        # Clamp index to valid range and insert
        index = max(0, min(index, len(self._widgets)))
        self._widgets.insert(index, widget)
        
        if widget.is_modal:
            log.debug(f"Manager.add_widget_at() added modal widget {widget.__class__.__name__} at index {index}")

        return self.update(full=False)
    
    def set_background(self, shade: int = 0) -> None:
        """Set the background shade level using dithering.
        
        Creates or updates a BackgroundWidget that renders a dithered pattern
        to simulate grayscale on the 1-bit display.
        
        Args:
            shade: Grayscale level 0-16 (0=white, 8=50% gray, 16=black)
        """
        from ..background import BackgroundWidget
        
        if self._background is None:
            self._background = BackgroundWidget(self._epd.width, self._epd.height, shade)
        else:
            self._background.set_shade(shade)
    
    def clear_background(self) -> None:
        """Clear the background (revert to plain white)."""
        self._background = None
    
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
            
            if widget.is_modal:
                log.debug(f"Manager.remove_widget() removed modal widget {widget.__class__.__name__}")
            else:
                log.debug(f"Manager.remove_widget() removed {widget.__class__.__name__}")
            
            return self.update(full=False)
        else:
            log.debug(f"Manager.remove_widget() widget {widget.__class__.__name__} not found")
            return None
    
    def clear_widgets(self, addStatusBar: bool = True) -> Future:
        """Clear all widgets from the display.
        
        Stops all widget background threads, clears the widget list, and
        clears any pending refresh requests to prevent stale updates.
        """
        log.debug(f"Manager.clear_widgets() called, clearing {len(self._widgets)} widgets")
        
        # Clear pending refresh requests first to prevent stale updates
        # from widgets that are about to be removed
        self._scheduler.clear_pending()
        
        # Stop all existing widgets before clearing to prevent background threads from continuing
        for widget in self._widgets:
            try:
                widget.stop()
            except Exception as e:
                log.debug(f"Error stopping widget {widget.__class__.__name__} during clear: {e}")
            # Clear the widget's update callback to prevent stale updates
            try:
                widget.set_update_callback(None)
            except Exception:
                pass
        
        self._widgets.clear()
        
        # Create and add status bar widget
        if addStatusBar:
            status_bar_widget = StatusBarWidget(0, 0)
            return self.add_widget(status_bar_widget)

        return None
    
    def update(self, full: bool = False) -> Future:
        """Update the display with current widget states.
        
        If any widget has is_modal=True, only that widget is rendered.
        Otherwise, all visible widgets are rendered.
        
        Args:
            full: If True, force a full refresh instead of partial refresh.
        
        Returns:
            Future: A Future that completes when the display refresh finishes.
        """
        if full:
            log.debug(f"Manager.update() called with full=True (will cause flashing refresh)")
        
        if not self._initialized or self._shutting_down:
            from concurrent.futures import Future
            future = Future()
            future.set_result("not-initialized")
            return future
        
        # Get canvas and render background
        canvas = self._framebuffer.get_canvas()
        if self._background is not None:
            # Use dithered background widget
            self._background.draw_on(canvas, 0, 0)
        else:
            # Plain white background
            from PIL import ImageDraw
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((0, 0, self._epd.width, self._epd.height), fill=255)
        
        # Find if there's a modal widget
        modal_widget = None
        for widget in self._widgets:
            if widget.is_modal and widget.visible:
                modal_widget = widget
                break
        
        # Draw all visible non-modal widgets in z-order (first = bottom, last = top)
        for widget in self._widgets:
            if not widget.visible:
                continue
            if widget.is_modal:
                continue  # Modal drawn last, on top
            log.debug(f"Manager._do_update(): Rendering {widget.__class__.__name__} at ({widget.x}, {widget.y}) size {widget.width}x{widget.height}")
            widget.draw_on(canvas, widget.x, widget.y)
        
        # Draw modal widget last (on top of everything)
        if modal_widget:
            modal_widget.draw_on(canvas, modal_widget.x, modal_widget.y)
        
        # CRITICAL: Capture snapshot of framebuffer state at this exact moment
        # This ensures each update request carries its own image state, so rapid
        # updates display all intermediate states, not just the final one
        snapshot = self._framebuffer.snapshot(rotation=epdconfig.ROTATION)
        
        # Submit refresh with the captured snapshot and return Future
        # The on_refresh callback is invoked by Scheduler after display update
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
