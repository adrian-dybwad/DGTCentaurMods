"""
ePaper display framework.
"""

from .display_manager import DisplayManager
from .widget import Widget
from .widgets import ClockWidget, BatteryWidget, TextWidget, BallWidget

__all__ = ['DisplayManager', 'Widget', 'ClockWidget', 'BatteryWidget', 'TextWidget', 'BallWidget']
