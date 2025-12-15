"""
Status bar widget displaying time, Chromecast, WiFi, Bluetooth, and battery icons.
"""

from PIL import Image
from .framework.widget import Widget
from .clock import ClockWidget
from .wifi_status import WiFiStatusWidget
from .bluetooth_status import BluetoothStatusWidget
from .battery import BatteryWidget
from .chromecast_status import ChromecastStatusWidget, set_chromecast_widget
import os
from typing import List

# Status bar height constant
STATUS_BAR_HEIGHT = 16

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class StatusBarWidget(Widget):
    """Status bar widget displaying time, Chromecast, WiFi, Bluetooth, and battery icons.
    
    Layout (128px wide, 16px tall) - right-aligned icons:
    - Clock: x=2, width=56 (HH:MM format)
    - Chromecast: x=60, width=14 (only visible when streaming)
    - WiFi: x=76, width=14
    - Bluetooth: x=92, width=14
    - Battery: x=108, width=20
    
    When Chromecast is streaming, the cast icon appears at x=60, right before WiFi.
    """
    
    # Fixed positions (right-aligned icons) - total: 128px
    CHROMECAST_X = 60   # Chromecast position (14px wide, only when streaming)
    WIFI_X = 76         # WiFi position (14px wide)
    BLUETOOTH_X = 92    # Bluetooth position (14px wide)
    BATTERY_X = 108     # Battery at far right (20px wide, ends at 128)
    
    def __init__(self, x: int = 0, y: int = 0):
        super().__init__(x, y, 128, STATUS_BAR_HEIGHT)
        
        # Create clock widget with HH:MM format, 14pt font
        font_path = '/opt/DGTCentaurMods/resources/Font.ttc'
        if not os.path.exists(font_path):
            font_path = 'resources/Font.ttc'
        self._clock_widget = ClockWidget(2, 0, width=56, height=16, 
                                         font_size=14, font_path=font_path,
                                         show_seconds=False)
        
        # Chromecast status widget (hidden when not streaming)
        self._chromecast_widget = ChromecastStatusWidget(self.CHROMECAST_X, 1, size=14)
        set_chromecast_widget(self._chromecast_widget)
        
        # Other status widgets
        self._wifi_widget = WiFiStatusWidget(self.WIFI_X, 1, size=14)
        self._bluetooth_widget = BluetoothStatusWidget(self.BLUETOOTH_X, 1, size=14)
        self._battery_widget = BatteryWidget(self.BATTERY_X, 1, width=20, height=14)
        
        # Collect all child widgets for unified lifecycle management
        self._child_widgets: List[Widget] = [
            self._clock_widget,
            self._chromecast_widget,
            self._wifi_widget,
            self._bluetooth_widget,
            self._battery_widget,
        ]
        
        # Start battery widget polling thread
        self._battery_widget.start()
    
    def set_scheduler(self, scheduler) -> None:
        """Set scheduler and propagate to all child widgets."""
        super().set_scheduler(scheduler)
        for widget in self._child_widgets:
            widget.set_scheduler(scheduler)
    
    def set_update_callback(self, callback) -> None:
        """Set update callback and propagate to all child widgets."""
        super().set_update_callback(callback)
        for widget in self._child_widgets:
            widget.set_update_callback(callback)
    
    def invalidate(self) -> None:
        """Invalidate the widget cache to force re-render on next update."""
        self._last_rendered = None
    
    def update(self, full: bool = False):
        """Invalidate cache and request display update.
        
        Args:
            full: If True, force a full refresh instead of partial refresh.
        
        Returns:
            Future that completes when the display refresh finishes.
        """
        self.invalidate()
        return self.request_update(full=full)
    
    def stop(self) -> None:
        """Stop all child widgets and perform cleanup."""
        for widget in self._child_widgets:
            try:
                widget.stop()
            except Exception as e:
                log.debug(f"Error stopping {widget.__class__.__name__}: {e}")
    
    @property
    def chromecast_widget(self) -> ChromecastStatusWidget:
        """Access the Chromecast status widget for starting/stopping streams."""
        return self._chromecast_widget
    
    def draw_on(self, img: Image.Image, draw_x: int, draw_y: int) -> None:
        """Draw status bar with all visible child widgets.
        
        Order from left to right: Clock, [Chromecast], WiFi, Bluetooth, Battery
        Each widget controls its own visibility.
        """
        # Draw background (white)
        self.draw_background(img, draw_x, draw_y)
        
        # Draw all visible child widgets
        for widget in self._child_widgets:
            if widget.visible:
                widget.draw_on(img, draw_x + widget.x, draw_y + widget.y)
