# Players Module
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Players are entities that make moves in a chess game. Each game has two
# players (White and Black). A player can be:
# - Human: moves come from the physical board
# - Engine: moves come from a UCI engine
# - Lichess: moves come from the Lichess server
#
# All players receive piece events and submit moves via callback:
# - HumanPlayer: Forms move from lift/place, submits any move
# - EnginePlayer: Computes move, only submits if piece events match
# - LichessPlayer: Receives move from server, only submits if piece events match
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from .base import Player, PlayerConfig, PlayerState, PlayerType
from .human import HumanPlayer, HumanPlayerConfig
from .engine import EnginePlayer, EnginePlayerConfig, create_engine_player
from .lichess import LichessPlayer, LichessPlayerConfig, LichessGameMode, create_lichess_player
from .manager import PlayerManager

__all__ = [
    # Base classes
    'Player',
    'PlayerConfig',
    'PlayerState',
    'PlayerType',
    # Human player
    'HumanPlayer',
    'HumanPlayerConfig',
    # Engine player
    'EnginePlayer',
    'EnginePlayerConfig',
    'create_engine_player',
    # Lichess player
    'LichessPlayer',
    'LichessPlayerConfig',
    'LichessGameMode',
    'create_lichess_player',
    # Manager
    'PlayerManager',
]
