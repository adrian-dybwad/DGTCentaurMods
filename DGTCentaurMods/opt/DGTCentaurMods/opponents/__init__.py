# Opponents Module
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Opponents are entities that play against the user. They provide moves
# in response to the user's moves. Examples: chess engines, online opponents
# (Lichess), or a null opponent for two-player mode.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from .base import Opponent, OpponentConfig, OpponentState
from .engine import EngineOpponent, EngineConfig, create_engine_opponent
from .human import HumanOpponent, HumanConfig
from .lichess import LichessOpponent, LichessConfig, LichessGameMode, create_lichess_opponent

__all__ = [
    # Base classes
    'Opponent',
    'OpponentConfig', 
    'OpponentState',
    # Engine opponent
    'EngineOpponent',
    'EngineConfig',
    'create_engine_opponent',
    # Human opponent (two-player)
    'HumanOpponent',
    'HumanConfig',
    # Lichess opponent
    'LichessOpponent',
    'LichessConfig',
    'LichessGameMode',
    'create_lichess_opponent',
]
