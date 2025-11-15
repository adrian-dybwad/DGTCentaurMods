# DGTCentaurMods Games Module
"""
Games module for managing chess games and UCI engine interactions.

This module provides:
- GameManager: Core game state management and move processing
- UCI game mode: Pure UCI engine play without adaptive features
"""

from DGTCentaurMods.games.manager import GameManager
from DGTCentaurMods.games.uci import run_uci_game

__all__ = ['GameManager', 'run_uci_game']

