"""
Games module for chess game management and UCI engine interface.

This module provides clean, refactored implementations of chess game
management and UCI engine interfaces.
"""

from DGTCentaurMods.games.manager import GameManager, GameEvent
from DGTCentaurMods.games.uci import UCIEngine

__all__ = ['GameManager', 'GameEvent', 'UCIEngine']

