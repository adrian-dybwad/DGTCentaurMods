"""
Games module for chess game management.

This module provides a clean, event-driven architecture for managing chess games
with proper separation of concerns between game state management and UI/engine logic.
"""

from DGTCentaurMods.games.manager import ChessGameManager, GameEvent
from DGTCentaurMods.games.uci import UCIEngineController

__all__ = ['ChessGameManager', 'GameEvent', 'UCIEngineController']
