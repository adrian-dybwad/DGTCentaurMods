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
from .checkerboard import CheckerboardWidget
from .welcome import WelcomeWidget
from .status_bar import StatusBarWidget
from .wifi_status import WiFiStatusWidget
from .game_over import GameOverWidget
from .menu_arrow import MenuArrowWidget

__all__ = ['Manager', 'Widget', 'ClockWidget', 'BatteryWidget', 'TextWidget', 'BallWidget', 
           'ChessBoardWidget', 'GameAnalysisWidget', 'CheckerboardWidget', 'WelcomeWidget', 
           'StatusBarWidget', 'WiFiStatusWidget', 'GameOverWidget', 'MenuArrowWidget']
