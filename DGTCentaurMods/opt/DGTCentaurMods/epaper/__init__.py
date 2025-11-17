"""
ePaper display framework.
"""

from .framework import Manager, Widget
from .clock import ClockWidget
from .battery import BatteryWidget
from .text import TextWidget
from .ball import BallWidget
from .chess_board import ChessBoardWidget
from .game_analysis import GameAnalysisWidget

__all__ = ['Manager', 'Widget', 'ClockWidget', 'BatteryWidget', 'TextWidget', 'BallWidget', 
           'ChessBoardWidget', 'GameAnalysisWidget']
