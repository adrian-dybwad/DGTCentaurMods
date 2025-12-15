"""
Status bar widget displaying time, WiFi status, and battery icon.
"""

from PIL import Image
from .framework.widget import Widget
from .clock import ClockWidget
from .wifi_status import WiFiStatusWidget
from .battery import BatteryWidget
import os

# Status bar height constant
STATUS_BAR_HEIGHT = 16

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class StatusBarWidget(Widget):
    """Status bar widget displaying time, WiFi status, and battery icon."""
    
    def __init__(self, x: int = 0, y: int = 0):
        super().__init__(x, y, 128, STATUS_BAR_HEIGHT)
        # Create clock widget with HH:MM:SS format (showing seconds), 14pt font
        font_path = '/opt/DGTCentaurMods/resources/Font.ttc'
        if not os.path.exists(font_path):
            font_path = 'resources/Font.ttc'
        self._clock_widget = ClockWidget(2, 0, width=76, height=16, 
                                         font_size=14, font_path=font_path,
                                         show_seconds=False)
        self._wifi_widget = WiFiStatusWidget(80, 0)
        self._battery_widget = BatteryWidget(98, 1)  # 30x14, ends at x=128
        # Start battery widget polling thread
        self._battery_widget.start()
    
    def set_scheduler(self, scheduler) -> None:
        """Set scheduler and propagate to child widgets."""
        super().set_scheduler(scheduler)
        # Propagate scheduler to child widgets so they can trigger updates
        self._clock_widget.set_scheduler(scheduler)
        self._wifi_widget.set_scheduler(scheduler)
        self._battery_widget.set_scheduler(scheduler)
    
    def set_update_callback(self, callback) -> None:
        """Set update callback and propagate to child widgets."""
        super().set_update_callback(callback)
        # Propagate callback to child widgets so they can trigger updates
        self._clock_widget.set_update_callback(callback)
        self._wifi_widget.set_update_callback(callback)
        self._battery_widget.set_update_callback(callback)
    
    def invalidate(self) -> None:
        """Invalidate the widget cache to force re-render on next update."""
        self._last_rendered = None
    
    def update(self, full: bool = False):
        """Invalidate cache and request display update.
        
        Args:
            full: If True, force a full refresh instead of partial refresh.
        
        Returns:
            Future: A Future that completes when the display refresh finishes.
        """
        self.invalidate()
        return self.request_update(full=full)
    
    def stop(self) -> None:
        """Stop the widget and perform cleanup tasks."""
        # Stop all child widgets
        try:
            self._clock_widget.stop()
        except Exception as e:
            log.debug(f"Error stopping clock widget: {e}")
        
        try:
            self._wifi_widget.stop()
        except Exception as e:
            log.debug(f"Error stopping WiFi widget: {e}")
        
        try:
            self._battery_widget.stop()
        except Exception as e:
            log.debug(f"Error stopping battery widget: {e}")
    
    def draw_on(self, img: Image.Image, draw_x: int, draw_y: int) -> None:
        """Draw status bar with time, WiFi status, and battery icon."""
        # Draw background (white)
        self.draw_background(img, draw_x, draw_y)
        
        # Draw time using ClockWidget
        self._clock_widget.draw_on(img, draw_x + self._clock_widget.x, draw_y + self._clock_widget.y)
        
        # Draw WiFi status icon (to the left of battery)
        self._wifi_widget.draw_on(img, draw_x + 80, draw_y + 0)
        
        # Draw battery icon using BatteryWidget (polls its own state)
        self._battery_widget.draw_on(img, draw_x + 98, draw_y + 1)

