"""
Status bar widget displaying time, WiFi status, and battery icon.
"""

from PIL import Image
from .framework.widget import Widget
from .clock import ClockWidget
from .wifi_status import WiFiStatusWidget
from .battery import BatteryWidget
import os

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class StatusBarWidget(Widget):
    """Status bar widget displaying time, WiFi status, and battery icon."""
    
    def __init__(self, x: int = 0, y: int = 0):
        super().__init__(x, y, 128, 16)
        # Create clock widget with HH:MM:SS format (showing seconds), 14pt font
        font_path = '/opt/DGTCentaurMods/resources/Font.ttc'
        if not os.path.exists(font_path):
            font_path = 'resources/Font.ttc'
        self._clock_widget = ClockWidget(2, 0, width=76, height=16, 
                                         format="%H:%M:%S", font_size=14, font_path=font_path,
                                         show_seconds=True)
        self._wifi_widget = WiFiStatusWidget(80, 0)
        self._battery_widget = BatteryWidget(98, 1)
    
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
    
    def render(self) -> Image.Image:
        """Render status bar with time, WiFi status, and battery icon."""
        img = Image.new("1", (self.width, self.height), 255)
        
        # Draw time using ClockWidget
        clock_image = self._clock_widget.render()
        img.paste(clock_image, (self._clock_widget.x, self._clock_widget.y))
        
        # Draw WiFi status icon (to the left of battery)
        wifi_icon = self._wifi_widget.render()
        img.paste(wifi_icon, (80, 0))
        
        # Draw battery icon using BatteryWidget
        # Update battery widget from board state before rendering
        self._battery_widget.update_from_board()
        battery_icon = self._battery_widget.render()
        img.paste(battery_icon, (98, 1))
        
        return img

