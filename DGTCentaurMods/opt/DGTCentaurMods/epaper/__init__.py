"""
ePaper display framework.
"""

from .manager import Manager
from .widget import Widget
from .widgets import ClockWidget, BatteryWidget, TextWidget, BallWidget

__all__ = ['Manager', 'Widget', 'ClockWidget', 'BatteryWidget', 'TextWidget', 'BallWidget']
