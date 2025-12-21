"""
State module - lightweight observable state objects.

State objects hold application data with observer patterns for change notifications.
"""

from .chess_game import ChessGameState, get_chess_game
from .chess_clock import ChessClockState, get_chess_clock
from .chromecast import ChromecastState, get_chromecast
from .system import SystemState, get_system
from .analysis import AnalysisState, get_analysis

__all__ = [
    'ChessGameState', 'get_chess_game',
    'ChessClockState', 'get_chess_clock',
    'ChromecastState', 'get_chromecast',
    'SystemState', 'get_system',
    'AnalysisState', 'get_analysis',
]
