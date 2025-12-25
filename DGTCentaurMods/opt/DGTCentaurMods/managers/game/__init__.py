"""Game manager package.

This package uses lazy imports for the same reason as `DGTCentaurMods.managers`:
importing the package should not require hardware-specific dependencies.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "GameManager": ("DGTCentaurMods.managers.game.game_manager", "GameManager"),
    "MoveState": ("DGTCentaurMods.managers.game.move_state", "MoveState"),
    "CorrectionMode": ("DGTCentaurMods.managers.game.correction_mode", "CorrectionMode"),
    "write_fen_log": ("DGTCentaurMods.paths", "write_fen_log"),
    "EVENT_NEW_GAME": ("DGTCentaurMods.managers.events", "EVENT_NEW_GAME"),
    "EVENT_WHITE_TURN": ("DGTCentaurMods.managers.events", "EVENT_WHITE_TURN"),
    "EVENT_BLACK_TURN": ("DGTCentaurMods.managers.events", "EVENT_BLACK_TURN"),
    "EVENT_LIFT_PIECE": ("DGTCentaurMods.managers.events", "EVENT_LIFT_PIECE"),
    "EVENT_PLACE_PIECE": ("DGTCentaurMods.managers.events", "EVENT_PLACE_PIECE"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_LAZY_IMPORTS.keys()))


__all__ = list(_LAZY_IMPORTS.keys())


