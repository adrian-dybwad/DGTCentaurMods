"""
ePaper display framework.
"""

from .framework import Manager, Widget
from .clock import ClockWidget
from .battery import BatteryWidget
from .text import TextWidget
from .ball import BallWidget

__all__ = ['Manager', 'Widget', 'ClockWidget', 'BatteryWidget', 'TextWidget', 'BallWidget']
