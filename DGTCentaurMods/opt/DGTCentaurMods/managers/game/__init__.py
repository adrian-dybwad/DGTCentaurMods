"""Game manager package.

This package used to be a single large module at `DGTCentaurMods.managers.game`.
It is now a package to allow splitting responsibilities into focused modules,
while preserving the public import path and re-exported symbols.
"""

from DGTCentaurMods.managers.events import (
    EVENT_BLACK_TURN,
    EVENT_LIFT_PIECE,
    EVENT_NEW_GAME,
    EVENT_PLACE_PIECE,
    EVENT_WHITE_TURN,
)
from DGTCentaurMods.paths import write_fen_log

from .correction_mode import CorrectionMode
from .game_manager import GameManager
from .move_state import MoveState

__all__ = [
    "GameManager",
    "MoveState",
    "CorrectionMode",
    "write_fen_log",
    "EVENT_NEW_GAME",
    "EVENT_WHITE_TURN",
    "EVENT_BLACK_TURN",
    "EVENT_LIFT_PIECE",
    "EVENT_PLACE_PIECE",
]


