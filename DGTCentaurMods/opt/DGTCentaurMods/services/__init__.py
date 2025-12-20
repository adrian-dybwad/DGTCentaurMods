"""
Services module for long-lived singleton components.

Services manage application-level functionality that persists across UI state changes.
They own threads and resources, using state objects (from the state/ module) for
observable data.

For state access, import from state/ directly. For lifecycle control, use services.
"""

from .chromecast import ChromecastService, get_chromecast_service, write_epaper_jpg
from .chess_clock import ChessClockService, get_chess_clock_service, get_chess_clock
from .chess_game import ChessGameService, get_chess_game_service

__all__ = [
    'ChromecastService', 'get_chromecast_service', 'write_epaper_jpg',
    'ChessClockService', 'get_chess_clock_service', 'get_chess_clock',
    'ChessGameService', 'get_chess_game_service',
]
