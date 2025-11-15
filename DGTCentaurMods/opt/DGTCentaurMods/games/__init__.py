"""
Games package for DGTCentaur Mods.

Provides chess game management and UCI engine integration.
"""

from DGTCentaurMods.games.manager import GameManager, GameEvent
from DGTCentaurMods.games.uci import UCIHandler

__all__ = ['GameManager', 'GameEvent', 'UCIHandler']

