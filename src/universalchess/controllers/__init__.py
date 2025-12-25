"""
Controllers module.

Manages how games are controlled - whether from local players or external apps.
"""

from .base import GameController
from .local import LocalController
from .remote import RemoteController, CLIENT_UNKNOWN, CLIENT_MILLENNIUM, CLIENT_PEGASUS, CLIENT_CHESSNUT
from .manager import ControllerManager

__all__ = [
    'GameController',
    'LocalController',
    'RemoteController',
    'ControllerManager',
    'CLIENT_UNKNOWN',
    'CLIENT_MILLENNIUM',
    'CLIENT_PEGASUS',
    'CLIENT_CHESSNUT',
]
