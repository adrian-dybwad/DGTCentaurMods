# Managers Package
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Centralizes all manager classes for the application.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

import time as _t
import logging as _logging
_log = _logging.getLogger(__name__)
_s = _t.time()

from DGTCentaurMods.managers.menu import MenuManager, MenuSelection, MenuResult, is_break_result, find_entry_index
_log.debug(f"[managers import] menu: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.protocol import ProtocolManager
_log.debug(f"[managers import] protocol: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.ble import BleManager
_log.debug(f"[managers import] ble: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.relay import RelayManager
_log.debug(f"[managers import] relay: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.connection import ConnectionManager
_log.debug(f"[managers import] connection: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.display import DisplayManager
_log.debug(f"[managers import] display: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.rfcomm import RfcommManager
_log.debug(f"[managers import] rfcomm: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.game import (
    GameManager,
    EVENT_NEW_GAME,
    EVENT_WHITE_TURN,
    EVENT_BLACK_TURN,
    EVENT_LIFT_PIECE,
    EVENT_PLACE_PIECE,
)
_log.debug(f"[managers import] game: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.assistant import AssistantManager, AssistantManagerConfig, AssistantType
_log.debug(f"[managers import] assistant: {(_t.time() - _s)*1000:.0f}ms")

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
