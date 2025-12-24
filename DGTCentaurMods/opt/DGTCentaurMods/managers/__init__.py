"""Managers package.

This module intentionally uses lazy imports.

Rationale:
- Many managers transitively import hardware-specific modules (e-paper, GPIO, etc.).
- Unit tests and non-hardware environments must be able to import subpackages like
  `DGTCentaurMods.managers.game.move_state` without requiring Raspberry Pi-only deps.
- Lazy imports preserve the public API (`from DGTCentaurMods.managers import GameManager`)
  while avoiding side-effects at import time.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # menu
    "MenuManager": ("DGTCentaurMods.managers.menu", "MenuManager"),
    "MenuSelection": ("DGTCentaurMods.managers.menu", "MenuSelection"),
    "MenuResult": ("DGTCentaurMods.managers.menu", "MenuResult"),
    "is_break_result": ("DGTCentaurMods.managers.menu", "is_break_result"),
    "find_entry_index": ("DGTCentaurMods.managers.menu", "find_entry_index"),
    # protocol / connectivity
    "ProtocolManager": ("DGTCentaurMods.managers.protocol", "ProtocolManager"),
    "BleManager": ("DGTCentaurMods.managers.ble", "BleManager"),
    "RelayManager": ("DGTCentaurMods.managers.relay", "RelayManager"),
    "ConnectionManager": ("DGTCentaurMods.managers.connection", "ConnectionManager"),
    "RfcommManager": ("DGTCentaurMods.managers.rfcomm", "RfcommManager"),
    # display
    "DisplayManager": ("DGTCentaurMods.managers.display", "DisplayManager"),
    # game
    "GameManager": ("DGTCentaurMods.managers.game", "GameManager"),
    "EVENT_NEW_GAME": ("DGTCentaurMods.managers.game", "EVENT_NEW_GAME"),
    "EVENT_WHITE_TURN": ("DGTCentaurMods.managers.game", "EVENT_WHITE_TURN"),
    "EVENT_BLACK_TURN": ("DGTCentaurMods.managers.game", "EVENT_BLACK_TURN"),
    "EVENT_LIFT_PIECE": ("DGTCentaurMods.managers.game", "EVENT_LIFT_PIECE"),
    "EVENT_PLACE_PIECE": ("DGTCentaurMods.managers.game", "EVENT_PLACE_PIECE"),
    # assistant
    "AssistantManager": ("DGTCentaurMods.managers.assistant", "AssistantManager"),
    "AssistantManagerConfig": ("DGTCentaurMods.managers.assistant", "AssistantManagerConfig"),
    "AssistantType": ("DGTCentaurMods.managers.assistant", "AssistantType"),
}


def __getattr__(name: str) -> Any:
    """Lazily import manager symbols on first access."""
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

__all__ = [
    'MenuManager',
    'MenuSelection', 
    'MenuResult',
    'is_break_result',
    'find_entry_index',
    'ProtocolManager',
    'BleManager',
    'RelayManager',
    'ConnectionManager',
    'DisplayManager',
    'RfcommManager',
    'GameManager',
    'EVENT_NEW_GAME',
    'EVENT_WHITE_TURN',
    'EVENT_BLACK_TURN',
    'EVENT_LIFT_PIECE',
    'EVENT_PLACE_PIECE',
    'AssistantManager',
    'AssistantManagerConfig',
    'AssistantType',
]
