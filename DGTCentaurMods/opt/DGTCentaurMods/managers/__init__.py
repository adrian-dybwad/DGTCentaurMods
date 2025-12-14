# Managers Package
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Centralizes all manager classes for the application.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from typing import Protocol, Tuple, Optional

import time as _t
import logging as _logging
_log = _logging.getLogger(__name__)
_s = _t.time()


class DisplayBridge(Protocol):
    """Interface for display-related operations used by GameManager.
    
    This protocol defines the contract between GameManager and the display layer
    (typically DisplayManager). It consolidates all display-related callbacks
    into a single interface for cleaner dependency management.
    
    Implementations should handle None returns gracefully.
    """
    
    def get_clock_times(self) -> Tuple[Optional[int], Optional[int]]:
        """Get current clock times for both players.
        
        Returns:
            Tuple of (white_seconds, black_seconds), or (None, None) if unavailable.
        """
        ...
    
    def set_clock_times(self, white_seconds: int, black_seconds: int) -> None:
        """Set clock times (used by external sources like Lichess).
        
        Args:
            white_seconds: White's remaining time in seconds
            black_seconds: Black's remaining time in seconds
        """
        ...
    
    def get_eval_score(self) -> Optional[int]:
        """Get current evaluation score in centipawns.
        
        Returns:
            Evaluation in centipawns from white's perspective, or None if unavailable.
        """
        ...
    
    def update_position(self, fen: str) -> None:
        """Update the display with a new position.
        
        Args:
            fen: FEN string of the position to display
        """
        ...
    
    def show_check_alert(self, is_black_in_check: bool, attacker_square: int, king_square: int) -> None:
        """Show a check alert on the display.
        
        Args:
            is_black_in_check: True if black is in check, False if white
            attacker_square: Square index of the attacking piece
            king_square: Square index of the king in check
        """
        ...
    
    def show_queen_threat(self, is_black_queen_threatened: bool, attacker_square: int, queen_square: int) -> None:
        """Show a queen threat alert on the display.
        
        Args:
            is_black_queen_threatened: True if black's queen is threatened
            attacker_square: Square index of the attacking piece
            queen_square: Square index of the threatened queen
        """
        ...
    
    def clear_alerts(self) -> None:
        """Clear any active alerts from the display."""
        ...
    
    def analyze_position(self, board, is_first_move: bool = False, time_limit: float = 0.3) -> None:
        """Request analysis of a position.
        
        Args:
            board: chess.Board object to analyze
            is_first_move: If True, skip adding to history (starting position)
            time_limit: Analysis time limit in seconds
        """
        ...

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

from DGTCentaurMods.managers.asset import AssetManager
_log.debug(f"[managers import] asset: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.opponent import OpponentManager, OpponentManagerConfig, OpponentType
_log.debug(f"[managers import] opponent: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.assistant import AssistantManager, AssistantManagerConfig, AssistantType
_log.debug(f"[managers import] assistant: {(_t.time() - _s)*1000:.0f}ms")

__all__ = [
    'DisplayBridge',
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
    'AssetManager',
    'OpponentManager',
    'OpponentManagerConfig',
    'OpponentType',
    'AssistantManager',
    'AssistantManagerConfig',
    'AssistantType',
]
