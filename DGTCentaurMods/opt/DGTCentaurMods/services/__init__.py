"""
Services module for long-lived singleton components.

Services manage application-level functionality that persists across UI state changes.
Unlike widgets (which are display components created/destroyed with UI), services
have independent lifecycles and expose state that widgets can observe.
"""

from .chromecast import ChromecastService, get_chromecast_service
from .chess_clock import ChessClock, get_chess_clock

__all__ = [
    'ChromecastService', 'get_chromecast_service',
    'ChessClock', 'get_chess_clock',
]
