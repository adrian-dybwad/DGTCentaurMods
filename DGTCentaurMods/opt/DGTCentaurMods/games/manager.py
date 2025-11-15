"""
Chess game manager that handles game state, move validation, and board events.

This module manages a chess game, passing events and moves back to calling scripts via callbacks.
The calling script is expected to manage the display itself using epaper.py.

This file is part of the DGTCentaur Mods open source software
( https://github.com/EdNekebno/DGTCentaur )

DGTCentaur Mods is free software: you can redistribute
it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version.

DGTCentaur Mods is distributed in the hope that it will
be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this file.  If not, see

https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md

This and any other notices must remain intact and unaltered in any
distribution, modification, variant, or derivative of this software.
"""

from enum import IntEnum
from typing import Optional, Callable, List, Tuple
import threading
import time
import chess
import sys
import inspect
import numpy as np
from scipy.optimize import linear_sum_assignment
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func, select

from DGTCentaurMods.board import board
from DGTCentaurMods.display import epaper
from DGTCentaurMods.db import models
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log
import logging


class GameEvent(IntEnum):
    """Game event types."""
    NEW_GAME = 1
    BLACK_TURN = 2
    WHITE_TURN = 3
    REQUEST_DRAW = 4
    RESIGN_GAME = 5


class BoardConstants:
    """Board-related constants."""
    SIZE = 64
    WIDTH = 8
    PROMOTION_ROW_WHITE = 7
    PROMOTION_ROW_BLACK = 0
    INVALID_SQUARE = -1


class ClockConstants:
    """Clock-related constants."""
    SECONDS_PER_MINUTE = 60
    DECREMENT_SECONDS = 2
    DISPLAY_LINE = 13


class MoveConstants:
    """Move-related constants."""
    MIN_UCI_LENGTH = 4


class GameConstants:
    """Game-related constants."""
    STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class CorrectionMode:
    """Manages correction mode state for board validation."""
    
    def __init__(self):
        self.is_active = False
        self.expected_state: Optional[bytearray] = None
        self.just_exited = False
    
    def enter(self, expected_state: Optional[bytearray]):
        """Enter correction mode with expected board state."""
        self.is_active = True
        self.expected_state = expected_state
        self.just_exited = False
        log.warning("[GameManager] Entered correction mode")
    
    def exit(self):
        """Exit correction mode."""
        self.is_active = False
        self.expected_state = None
        self.just_exited = True
        log.warning("[GameManager] Exited correction mode")


class MoveState:
    """Manages move-related state during move execution."""
    
    def __init__(self):
        self.source_square = BoardConstants.INVALID_SQUARE
        self.other_source_square = BoardConstants.INVALID_SQUARE
        self.legal_squares: List[int] = []
        self.computer_move = ""
        self.is_forced = False
    
    def reset(self):
        """Reset all move state variables."""
        self.source_square = BoardConstants.INVALID_SQUARE
        self.other_source_square = BoardConstants.INVALID_SQUARE
        self.legal_squares = []
        self.computer_move = ""
        self.is_forced = False


class GameInfo:
    """Stores game metadata for PGN files."""
    
    def __init__(self):
        self.event = ""
        self.site = ""
        self.round = ""
        self.white = ""
        self.black = ""


class GameManager:
    """
    Manages chess game state, move validation, and board events.
    
    This class encapsulates all game state and provides a clean interface
    for managing chess games with callbacks for events, moves, and key presses.
    """
    
    def __init__(self):
        """Initialize the game manager with default state."""
        # Chess board state
        self.chess_board = chess.Board()
        
        # Board state history for takeback detection
        self.board_state_history: List[bytearray] = []
        self.starting_state = bytearray(
            b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
        )
        
        # Callbacks
        self.event_callback: Optional[Callable] = None
        self.move_callback: Optional[Callable] = None
        self.key_callback: Optional[Callable] = None
        self.takeback_callback: Optional[Callable] = None
        
        # Game state
        self.move_state = MoveState()
        self.correction_mode = CorrectionMode()
        self.game_info = GameInfo()
        self.is_in_menu = False
        self.is_showing_promotion = False
        
        # Database
        self.database_session: Optional[sessionmaker] = None
        self.current_game_id: Optional[int] = None
        self.source_file: Optional[str] = None
        
        # Clock
        self.white_time_seconds = 0
        self.black_time_seconds = 0
        self.clock_thread: Optional[threading.Thread] = None
        
        # Threading
        self.game_thread: Optional[threading.Thread] = None
        self.should_stop = False
    
    def _collect_board_state(self):
        """Collect current board state and add to history."""
        log.info("[GameManager] Collecting board state")
        current_state = board.getChessState()
        self.board_state_history.append(current_state)
        log.debug(f"[GameManager] Board state collected. FEN: {self.chess_board.fen()}")
    
    def _wait_for_promotion_choice(self) -> str:
        """
        Wait for user to select promotion piece via button press.
        
        Returns:
            str: Promotion piece suffix ("q", "r", "b", "n") or "q" on timeout
        """
        key = board.wait_for_key_up(timeout=60)
        if key == board.Key.BACK:
            return "n"  # Knight
        elif key == board.Key.TICK:
            return "b"  # Bishop
        elif key == board.Key.UP:
            return "q"  # Queen
        elif key == board.Key.DOWN:
            return "r"  # Rook
        else:
            return "q"  # Default to queen on timeout/other
    
    def _check_takeback(self) -> bool:
        """
        Check if a takeback is in progress by comparing current state with previous state.
        
        Returns:
            bool: True if takeback detected and processed, False otherwise
        """
        if self.takeback_callback is None or len(self.board_state_history) <= 1:
            return False
        
        log.info("[GameManager] Checking for takeback")
        current_state = board.getChessState()
        previous_state = self.board_state_history[-2]
        
        log.debug("[GameManager] Current board state:")
        board.printChessState(current_state)
        log.debug("[GameManager] Previous board state:")
        board.printChessState(previous_state)
        
        if bytearray(current_state) == bytearray(previous_state):
            # Takeback detected
            board.ledsOff()
            self.board_state_history.pop()
            
            # Remove last move from database
            last_move = self.database_session.query(models.GameMove).order_by(
                models.GameMove.id.desc()
            ).first()
            if last_move:
                self.database_session.delete(last_move)
                self.database_session.commit()
            
            # Pop move from chess board
            self.chess_board.pop()
            paths.write_fen_log(self.chess_board.fen())
            
            board.beep(board.SOUND_GENERAL)
            if self.takeback_callback:
                self.takeback_callback()
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            current = board.getChessState()
            if not self._validate_board_state(current, self.board_state_history[-1] if self.board_state_history else None):
                log.warning("[GameManager] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            return True
        
        return False
    
    def _validate_board_state(
        self, 
        current_state: Optional[bytearray], 
        expected_state: Optional[bytearray]
    ) -> bool:
        """
        Validate board state by comparing piece presence.
        
        Args:
            current_state: Current board state from getChessState()
            expected_state: Expected board state to compare against
        
        Returns:
            bool: True if states match, False otherwise
        """
        if current_state is None or expected_state is None:
            return False
        
        if len(current_state) != BoardConstants.SIZE or len(expected_state) != BoardConstants.SIZE:
            return False
        
        return bytearray(current_state) == bytearray(expected_state)
    
    def _uci_to_squares(self, uci_move: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Convert UCI move string to square indices.
        
        Args:
            uci_move: UCI move string (e.g., "e2e4")
        
        Returns:
            tuple: (from_square, to_square) as integers (0-63), or (None, None) if invalid
        """
        if len(uci_move) < MoveConstants.MIN_UCI_LENGTH:
            return None, None
        
        from_square = (
            ((ord(uci_move[1:2]) - ord("1")) * BoardConstants.WIDTH) + 
             (ord(uci_move[0:1]) - ord("a"))
        )
        to_square = (
            ((ord(uci_move[3:4]) - ord("1")) * BoardConstants.WIDTH) + 
             (ord(uci_move[2:3]) - ord("a"))
        )
        
        return from_square, to_square
    
    def _trigger_turn_event(self):
        """Trigger appropriate event callback based on current turn."""
        if self.event_callback is None:
            return
        
        if self.chess_board.turn == chess.WHITE:
            self.event_callback(GameEvent.WHITE_TURN)
        else:
            self.event_callback(GameEvent.BLACK_TURN)
    
    def _update_game_result(self, result_str: str, termination: str, context: str = ""):
        """
        Update game result in database and trigger event callback.
        
        Args:
            result_str: Result string (e.g., "1-0", "0-1", "1/2-1/2")
            termination: Termination string for event callback
            context: Context string for logging (function name)
        """
        if self.current_game_id is not None:
            game = self.database_session.query(models.Game).filter(
                models.Game.id == self.current_game_id
            ).first()
            if game is not None:
                game.result = result_str
                self.database_session.flush()
                self.database_session.commit()
            else:
                log.warning(
                    f"[GameManager.{context}] Game with id {self.current_game_id} "
                    f"not found in database, cannot update result"
                )
        
        # Always trigger callback, even if DB update failed
        if self.event_callback is not None:
            self.event_callback(termination)
    
    def _handle_promotion(self, target_square: int, piece_symbol: str, is_forced: bool) -> str:
        """
        Handle pawn promotion by prompting user for piece choice.
        
        Args:
            target_square: Target square index
            piece_symbol: Piece symbol ("P" for white, "p" for black)
            is_forced: Whether this is a forced move (no user prompt)
        
        Returns:
            str: Promotion piece suffix ("q", "r", "b", "n") or empty string
        """
        # Check if promotion is needed
        is_white_promotion = (
            (target_square // BoardConstants.WIDTH) == BoardConstants.PROMOTION_ROW_WHITE and 
            piece_symbol == "P"
        )
        is_black_promotion = (
            (target_square // BoardConstants.WIDTH) == BoardConstants.PROMOTION_ROW_BLACK and 
            piece_symbol == "p"
        )
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        if not is_forced:
            screen_backup = epaper.epaperbuffer.copy()
            self.is_showing_promotion = True
            epaper.promotionOptions(ClockConstants.DISPLAY_LINE)
            promotion_choice = self._wait_for_promotion_choice()
            self.is_showing_promotion = False
            epaper.epaperbuffer = screen_backup.copy()
            return promotion_choice
        
        return ""
    
    def _format_time(self, white_seconds: int, black_seconds: int) -> str:
        """
        Format time display string for clock.
        
        Args:
            white_seconds: White player's remaining seconds
            black_seconds: Black player's remaining seconds
        
        Returns:
            str: Formatted time string "MM:SS       MM:SS"
        """
        white_minutes = white_seconds // ClockConstants.SECONDS_PER_MINUTE
        white_secs = white_seconds % ClockConstants.SECONDS_PER_MINUTE
        black_minutes = black_seconds // ClockConstants.SECONDS_PER_MINUTE
        black_secs = black_seconds % ClockConstants.SECONDS_PER_MINUTE
        
        return (
            f"{white_minutes:02d}:{white_secs:02d}       "
            f"{black_minutes:02d}:{black_secs:02d}"
        )
    
    def _calculate_legal_squares(self, source_square: int) -> List[int]:
        """
        Calculate legal destination squares for a piece at the given square.
        
        Args:
            source_square: Source square index (0-63)
        
        Returns:
            list: List of legal destination square indices, including the source square
        """
        legal_squares = [source_square]  # Include source square
        
        for move in self.chess_board.legal_moves:
            if move.from_square == source_square:
                legal_squares.append(move.to_square)
        
        return legal_squares
    
    def _reset_move_state(self):
        """Reset move-related state variables after a move is completed."""
        self.move_state.reset()
        board.ledsOff()
    
    def _double_beep(self):
        """Play two beeps with a short delay between them."""
        board.beep(board.SOUND_GENERAL)
        time.sleep(0.3)
        board.beep(board.SOUND_GENERAL)
    
    def _enter_correction_mode(self):
        """Enter correction mode to guide user in fixing board state."""
        expected_state = (
            self.board_state_history[-1] 
            if self.board_state_history 
            else None
        )
        self.correction_mode.enter(expected_state)
        log.warning(
            f"[GameManager] Entered correction mode "
            f"(is_forced={self.move_state.is_forced}, "
            f"computer_move={self.move_state.computer_move})"
        )
    
    def _exit_correction_mode(self):
        """Exit correction mode and resume normal game flow."""
        self.correction_mode.exit()
        
        # Reset move state variables to ensure clean state after correction
        self.move_state.source_square = BoardConstants.INVALID_SQUARE
        self.move_state.legal_squares = []
        self.move_state.other_source_square = BoardConstants.INVALID_SQUARE
        
        # If there was a forced move pending, restore the LEDs
        if (self.move_state.is_forced and 
            self.move_state.computer_move and 
            len(self.move_state.computer_move) >= MoveConstants.MIN_UCI_LENGTH):
            from_square, to_square = self._uci_to_squares(self.move_state.computer_move)
            if from_square is not None and to_square is not None:
                board.ledFromTo(from_square, to_square)
                log.info(
                    f"[GameManager] Restored forced move LEDs: "
                    f"{self.move_state.computer_move}"
                )
    
    def _provide_correction_guidance(
        self, 
        current_state: bytearray, 
        expected_state: bytearray
    ):
        """
        Provide LED guidance to correct misplaced pieces using Hungarian algorithm.
        
        Computes optimal pairing between misplaced pieces using linear_sum_assignment
        for minimal total movement distance, then lights up LEDs to guide the user.
        
        Args:
            current_state: Current board state from getChessState()
            expected_state: Expected board state
        """
        if current_state is None or expected_state is None:
            return
        
        if (len(current_state) != BoardConstants.SIZE or 
            len(expected_state) != BoardConstants.SIZE):
            return
        
        def square_to_row_col(square_idx: int) -> Tuple[int, int]:
            """Convert square index to (row, col)."""
            return (square_idx // BoardConstants.WIDTH), (square_idx % BoardConstants.WIDTH)
        
        def manhattan_distance(square_a: int, square_b: int) -> int:
            """Calculate Manhattan distance between two squares."""
            row_a, col_a = square_to_row_col(square_a)
            row_b, col_b = square_to_row_col(square_b)
            return abs(row_a - row_b) + abs(col_a - col_b)
        
        # Find misplaced pieces
        missing_squares = []  # Squares that should have pieces but don't
        wrong_squares = []    # Squares that have pieces but shouldn't
        
        for i in range(BoardConstants.SIZE):
            if expected_state[i] == 1 and current_state[i] == 0:
                missing_squares.append(i)
            elif expected_state[i] == 0 and current_state[i] == 1:
                wrong_squares.append(i)
        
        if len(missing_squares) == 0 and len(wrong_squares) == 0:
            # Board is correct
            board.ledsOff()
            return
        
        log.warning(
            f"[GameManager] Found {len(wrong_squares)} wrong pieces, "
            f"{len(missing_squares)} missing pieces"
        )
        
        # Guide one piece at a time
        if len(wrong_squares) > 0 and len(missing_squares) > 0:
            if len(wrong_squares) == 1 and len(missing_squares) == 1:
                # Simple case - just pair the only two
                from_idx = wrong_squares[0]
                to_idx = missing_squares[0]
            else:
                # Use Hungarian algorithm for optimal pairing
                n_wrong = len(wrong_squares)
                n_missing = len(missing_squares)
                
                # Create cost matrix based on Manhattan distances
                costs = np.zeros((n_wrong, n_missing))
                for i, wrong_sq in enumerate(wrong_squares):
                    for j, missing_sq in enumerate(missing_squares):
                        costs[i, j] = manhattan_distance(wrong_sq, missing_sq)
                
                # Find optimal assignment
                row_ind, col_ind = linear_sum_assignment(costs)
                
                # Guide the first pair
                from_idx = wrong_squares[row_ind[0]]
                to_idx = missing_squares[col_ind[0]]
            
            board.ledsOff()
            board.ledFromTo(from_idx, to_idx, intensity=5)
            log.warning(
                f"[GameManager] Guiding piece from {chess.square_name(from_idx)} "
                f"to {chess.square_name(to_idx)}"
            )
        else:
            # Only pieces missing or only extra pieces
            if len(missing_squares) > 0:
                # Light up the squares where pieces should be
                board.ledsOff()
                for idx in missing_squares:
                    board.led(idx, intensity=5)
                log.warning(
                    f"[GameManager] Pieces missing at: "
                    f"{[chess.square_name(sq) for sq in missing_squares]}"
                )
            elif len(wrong_squares) > 0:
                # Light up the squares where pieces shouldn't be
                board.ledsOff()
                for idx in wrong_squares:
                    board.led(idx, intensity=5)
                log.warning(
                    f"[GameManager] Extra pieces at: "
                    f"{[chess.square_name(sq) for sq in wrong_squares]}"
                )
    
    def _handle_field_callback_correction_mode(
        self, 
        piece_event: int, 
        field: int, 
        time_in_seconds: float
    ):
        """
        Handle field events during correction mode.
        
        Validates board state and only passes through to normal game flow when correct.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63)
            time_in_seconds: Time of the event
        """
        if not self.correction_mode.is_active:
            # Normal flow - pass through to original callback
            return self._handle_field_callback(piece_event, field, time_in_seconds)
        
        # In correction mode: check if board now matches expected after each event
        current_state = board.getChessState()
        
        # Check if board is in starting position (new game detection)
        if (current_state is not None and 
            len(current_state) == BoardConstants.SIZE):
            if bytearray(current_state) == self.starting_state:
                log.info(
                    "[GameManager] Starting position detected while in correction mode - "
                    "exiting correction and triggering new game check"
                )
                board.ledsOff()
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                self._reset_game()
                return
        
        log.debug("[GameManager] Current state:")
        board.printChessState(current_state, logging.ERROR)
        log.debug("[GameManager] Correction expected state:")
        board.printChessState(self.correction_mode.expected_state)
        
        if self._validate_board_state(current_state, self.correction_mode.expected_state):
            # Board is now correct!
            log.info("[GameManager] Board corrected, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            # Don't process this event through normal flow, just exit correction
            return
        
        # Still incorrect, update guidance
        self._provide_correction_guidance(current_state, self.correction_mode.expected_state)
    
    def _handle_key_callback(self, key_pressed):
        """
        Handle key press events.
        
        Receives the key pressed and passes back to the calling script.
        Exception: takes control of the HELP key to present draw/resign menu.
        
        Args:
            key_pressed: Key that was pressed
        """
        if self.key_callback is not None:
            if not self.is_in_menu and key_pressed != board.Key.HELP:
                self.key_callback(key_pressed)
            
            if not self.is_in_menu and key_pressed == board.Key.HELP:
                # Bring up the menu
                self.is_in_menu = True
                epaper.resignDrawMenu(14)
            
            if self.is_in_menu and key_pressed == board.Key.BACK:
                epaper.writeText(14, "                   ")
                self.is_in_menu = False
            
            if self.is_in_menu and key_pressed == board.Key.UP:
                epaper.writeText(14, "                   ")
                if self.event_callback:
                    self.event_callback(GameEvent.REQUEST_DRAW)
                self.is_in_menu = False
            
            if self.is_in_menu and key_pressed == board.Key.DOWN:
                epaper.writeText(14, "                   ")
                if self.event_callback:
                    self.event_callback(GameEvent.RESIGN_GAME)
                self.is_in_menu = False
    
    def _handle_field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """
        Handle field events (piece lift/place).
        
        Receives field events and uses them to calculate moves.
        piece_event: 0 = lift, 1 = place. Numbering 0 = a1, 63 = h8
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63)
            time_in_seconds: Time of the event
        """
        field_name = chess.square_name(field)
        piece_color = self.chess_board.color_at(field)
        
        log.info(
            f"[GameManager] piece_event={piece_event} field={field} "
            f"fieldname={field_name} color_at={'White' if piece_color else 'Black'} "
            f"time_in_seconds={time_in_seconds}"
        )
        
        is_lift = (piece_event == 0)
        is_place = (piece_event == 1)
        
        # Check if piece color matches current turn
        # vpiece = True if piece belongs to current player, False otherwise
        is_current_player_piece = (
            (self.chess_board.turn == chess.WHITE) == (piece_color == True)
        )
        
        # Handle piece lift
        if (is_lift and 
            field not in self.move_state.legal_squares and 
            self.move_state.source_square < 0 and 
            is_current_player_piece):
            # Generate a list of places this piece can move to
            self.move_state.legal_squares = self._calculate_legal_squares(field)
            self.move_state.source_square = field
        
        # Track opposing side lifts so we can guide returning them if moved
        if is_lift and not is_current_player_piece:
            self.move_state.other_source_square = field
        
        # If opponent piece is placed back on original square, turn LEDs off and reset
        if (is_place and 
            not is_current_player_piece and 
            self.move_state.other_source_square >= 0 and 
            field == self.move_state.other_source_square):
            board.ledsOff()
            self.move_state.other_source_square = BoardConstants.INVALID_SQUARE
        
        # Handle forced moves
        if self.move_state.is_forced and is_lift and is_current_player_piece:
            # If this is a forced move (computer move) then the piece lifted should
            # equal the start of computermove, otherwise set legalsquares so they can
            # just put the piece back down! If it is the correct piece then adjust
            # legalsquares so to only include the target square
            if field_name != self.move_state.computer_move[0:2]:
                # Forced move but wrong piece lifted
                self.move_state.legal_squares = [field]
            else:
                # Forced move, correct piece lifted, limit legal squares
                target = self.move_state.computer_move[2:4]
                target_square = chess.parse_square(target)
                self.move_state.legal_squares = [target_square]
        
        # Ignore PLACE events without a corresponding LIFT (stale events from before reset)
        if (is_place and 
            self.move_state.source_square < 0 and 
            self.move_state.other_source_square < 0):
            # After correction mode exits, there may be stale PLACE events
            if self.correction_mode.just_exited:
                # Check if this is the forced move source square
                if (self.move_state.is_forced and 
                    self.move_state.computer_move and 
                    len(self.move_state.computer_move) >= MoveConstants.MIN_UCI_LENGTH):
                    forced_source = chess.parse_square(self.move_state.computer_move[0:2])
                    if field != forced_source:
                        log.info(
                            f"[GameManager] Ignoring stale PLACE event after correction "
                            f"exit for field {field} (not forced move source)"
                        )
                        self.correction_mode.just_exited = False
                        return
                else:
                    log.info(
                        f"[GameManager] Ignoring stale PLACE event after correction "
                        f"exit for field {field}"
                    )
                    self.correction_mode.just_exited = False
                    return
            
            # For forced moves, also ignore stale PLACE events on the source square
            if (self.move_state.is_forced and 
                self.move_state.computer_move and 
                len(self.move_state.computer_move) >= MoveConstants.MIN_UCI_LENGTH):
                forced_source = chess.parse_square(self.move_state.computer_move[0:2])
                if field == forced_source:
                    log.info(
                        f"[GameManager] Ignoring stale PLACE event for forced move "
                        f"source field {field} (no corresponding LIFT)"
                    )
                    self.correction_mode.just_exited = False
                    return
            
            if not self.move_state.is_forced:
                log.info(
                    f"[GameManager] Ignoring stale PLACE event for field {field} "
                    f"(no corresponding LIFT)"
                )
                self.correction_mode.just_exited = False
                return
        
        # Clear the flag once we process a valid event (LIFT)
        if is_lift:
            self.correction_mode.just_exited = False
        
        # Handle illegal placement
        if is_place and field not in self.move_state.legal_squares:
            board.beep(board.SOUND_WRONG_MOVE)
            log.warning(f"[GameManager] Piece placed on illegal square {field}")
            is_takeback = self._check_takeback()
            if not is_takeback:
                self._guide_misplaced_piece(
                    field, 
                    self.move_state.source_square, 
                    self.move_state.other_source_square, 
                    is_current_player_piece
                )
        
        # Handle legal placement
        if is_place and field in self.move_state.legal_squares:
            log.info("[GameManager] Making move")
            if field == self.move_state.source_square:
                # Piece has simply been placed back
                board.ledsOff()
                self.move_state.source_square = BoardConstants.INVALID_SQUARE
                self.move_state.legal_squares = []
            else:
                # Piece has been moved - execute the move
                self._execute_move(field)
    
    def _execute_move(self, target_square: int):
        """
        Execute a chess move.
        
        Args:
            target_square: Target square index where piece was placed
        """
        from_name = chess.square_name(self.move_state.source_square)
        to_name = chess.square_name(target_square)
        piece_symbol = str(self.chess_board.piece_at(self.move_state.source_square))
        promotion_suffix = self._handle_promotion(
            target_square, 
            piece_symbol, 
            self.move_state.is_forced
        )
        
        if self.move_state.is_forced:
            move_uci = self.move_state.computer_move
        else:
            move_uci = from_name + to_name + promotion_suffix
        
        # Make the move and update fen.log
        try:
            self.chess_board.push(chess.Move.from_uci(move_uci))
            paths.write_fen_log(self.chess_board.fen())
            
            # Log move to database
            game_move = models.GameMove(
                gameid=self.current_game_id,
                move=move_uci,
                fen=str(self.chess_board.fen())
            )
            self.database_session.add(game_move)
            self.database_session.commit()
            
            self._collect_board_state()
            self._reset_move_state()
            
            if self.move_callback is not None:
                self.move_callback(move_uci)
            
            board.beep(board.SOUND_GENERAL)
            # Light up the square moved to
            board.led(target_square)
            
            # Check the outcome
            outcome = self.chess_board.outcome(claim_draw=True)
            if outcome is None:
                # Switch the turn
                self._trigger_turn_event()
            else:
                board.beep(board.SOUND_GENERAL)
                # Update game result in database and trigger callback
                result_str = str(self.chess_board.result())
                termination = str(outcome.termination)
                self._update_game_result(result_str, termination, "_execute_move")
        
        except ValueError as e:
            log.error(f"[GameManager] Invalid move {move_uci}: {e}")
            board.beep(board.SOUND_WRONG_MOVE)
            self._reset_move_state()
    
    def _guide_misplaced_piece(
        self, 
        field: int, 
        source_square: int, 
        other_source_square: int, 
        is_current_player_piece: bool
    ):
        """
        Guide the user to correct misplaced pieces using LED indicators.
        
        Args:
            field: The square where the illegal piece was placed
            source_square: The source square of the current player's piece being moved
            other_source_square: The source square of an opponent's piece that was lifted
            is_current_player_piece: Whether the piece belongs to the current player
        """
        log.warning(f"[GameManager] Entering correction mode for field {field}")
        self._enter_correction_mode()
        current_state = board.getChessState()
        if self.board_state_history:
            self._provide_correction_guidance(current_state, self.board_state_history[-1])
    
    def _reset_game(self):
        """Reset the game to starting position."""
        try:
            log.info("DEBUG: Detected starting position - triggering NEW_GAME")
            # Reset move-related state variables
            self.move_state.reset()
            self.chess_board.reset()
            paths.write_fen_log(self.chess_board.fen())
            self._double_beep()
            board.ledsOff()
            
            if self.event_callback:
                self.event_callback(GameEvent.NEW_GAME)
                self.event_callback(GameEvent.WHITE_TURN)
            
            # Log a new game in the database
            game = models.Game(
                source=self.source_file,
                event=self.game_info.event,
                site=self.game_info.site,
                round=self.game_info.round,
                white=self.game_info.white,
                black=self.game_info.black
            )
            log.info(game)
            self.database_session.add(game)
            self.database_session.commit()
            
            # Get the max game id as that is this game id
            self.current_game_id = self.database_session.query(
                func.max(models.Game.id)
            ).scalar()
            
            # Make an entry in GameMove for this start state
            game_move = models.GameMove(
                gameid=self.current_game_id,
                move='',
                fen=str(self.chess_board.fen())
            )
            self.database_session.add(game_move)
            self.database_session.commit()
            
            self.board_state_history = []
            self._collect_board_state()
        
        except Exception as e:
            log.error(f"Error resetting game: {e}")
            import traceback
            traceback.print_exc()
    
    def _game_thread(self):
        """Main thread that handles chess game functionality."""
        board.ledsOff()
        log.info("[GameManager] Subscribing to events")
        log.info("[GameManager] Keycallback: _handle_key_callback")
        log.info("[GameManager] Fieldcallback: _handle_field_callback_correction_mode")
        
        try:
            board.subscribeEvents(
                self._handle_key_callback, 
                self._handle_field_callback_correction_mode
            )
        except Exception as e:
            log.error(f"[GameManager] error: {e}")
            log.error(f"[GameManager] error: {sys.exc_info()[1]}")
            return
        
        while not self.should_stop:
            time.sleep(0.1)
    
    def _clock_thread(self):
        """Thread that decrements the clock and updates the display."""
        while not self.should_stop:
            time.sleep(ClockConstants.DECREMENT_SECONDS)
            
            # Decrement active player's time
            if (self.white_time_seconds > 0 and 
                self.chess_board.turn == chess.WHITE and 
                self.chess_board.fen() != GameConstants.STARTING_FEN):
                self.white_time_seconds -= ClockConstants.DECREMENT_SECONDS
            
            if (self.black_time_seconds > 0 and 
                self.chess_board.turn == chess.BLACK):
                self.black_time_seconds -= ClockConstants.DECREMENT_SECONDS
            
            if not self.is_showing_promotion:
                time_str = self._format_time(
                    self.white_time_seconds, 
                    self.black_time_seconds
                )
                epaper.writeText(ClockConstants.DISPLAY_LINE, time_str)
    
    def subscribe_game(
        self, 
        event_callback: Callable, 
        move_callback: Callable, 
        key_callback: Callable, 
        takeback_callback: Optional[Callable] = None
    ):
        """
        Subscribe to the game manager.
        
        Args:
            event_callback: Callback for game events
            move_callback: Callback for moves made
            key_callback: Callback for key presses
            takeback_callback: Optional callback for takebacks
        """
        self.event_callback = event_callback
        self.move_callback = move_callback
        self.key_callback = key_callback
        self.takeback_callback = takeback_callback
        
        self.board_state_history = []
        self._collect_board_state()
        
        self.source_file = inspect.getsourcefile(sys._getframe(1))
        Session = sessionmaker(bind=models.engine)
        self.database_session = Session()
        
        self.game_thread = threading.Thread(target=self._game_thread, args=())
        self.game_thread.daemon = True
        self.game_thread.start()
    
    def unsubscribe_game(self):
        """Stop the game manager and clean up resources."""
        board.ledsOff()
        self.should_stop = True
        
        # Clean up database session
        if self.database_session is not None:
            try:
                self.database_session.close()
                self.database_session = None
            except Exception:
                self.database_session = None
    
    def set_game_info(
        self, 
        event: str, 
        site: str, 
        round: str, 
        white: str, 
        black: str
    ):
        """
        Set game metadata for PGN files.
        
        Call before subscribing if you want to set further information about the game.
        
        Args:
            event: Event name
            site: Site name
            round: Round number
            white: White player name
            black: Black player name
        """
        self.game_info.event = event
        self.game_info.site = site
        self.game_info.round = round
        self.game_info.white = white
        self.game_info.black = black
    
    def computer_move(self, move_uci: str, forced: bool = True):
        """
        Set the computer move that the player is expected to make.
        
        Args:
            move_uci: Move in UCI format (e.g., "b2b4", "g7g8q")
            forced: Whether this is a forced move (default: True)
        """
        if len(move_uci) < MoveConstants.MIN_UCI_LENGTH:
            return
        
        self.move_state.computer_move = move_uci
        self.move_state.is_forced = forced
        
        # Indicate this on the board by converting UCI to square indices and lighting LEDs
        from_square, to_square = self._uci_to_squares(move_uci)
        if from_square is not None and to_square is not None:
            board.ledFromTo(from_square, to_square)
    
    def set_clock(self, white_seconds: int, black_seconds: int):
        """
        Set the clock times.
        
        Args:
            white_seconds: White player's time in seconds
            black_seconds: Black player's time in seconds
        """
        self.white_time_seconds = white_seconds
        self.black_time_seconds = black_seconds
    
    def start_clock(self):
        """Start the clock. It writes to CLOCK_DISPLAY_LINE."""
        time_str = self._format_time(self.white_time_seconds, self.black_time_seconds)
        epaper.writeText(ClockConstants.DISPLAY_LINE, time_str)
        self.clock_thread = threading.Thread(target=self._clock_thread, args=())
        self.clock_thread.daemon = True
        self.clock_thread.start()
    
    def resign_game(self, side_resigning: int):
        """
        Handle a resigned game.
        
        Args:
            side_resigning: 1 for white, 2 for black
        """
        result_str = "0-1" if side_resigning == 1 else "1-0"
        self._update_game_result(result_str, "Termination.RESIGN", "resign_game")
    
    def draw_game(self):
        """Handle a drawn game."""
        self._update_game_result("1/2-1/2", "Termination.DRAW", "draw_game")
    
    def get_result(self) -> str:
        """
        Look up the result of the last game and return it.
        
        Returns:
            str: Game result string or "Unknown" if no game found
        """
        game_data = self.database_session.execute(
            select(
                models.Game.created_at, 
                models.Game.source, 
                models.Game.event, 
                models.Game.site, 
                models.Game.round,
                models.Game.white, 
                models.Game.black, 
                models.Game.result, 
                models.Game.id
            ).order_by(models.Game.id.desc())
        ).first()
        
        if game_data is not None:
            return str(game_data.result)
        else:
            return "Unknown"
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self.chess_board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self.chess_board.fen()
    
    def reset_move_state(self):
        """Reset all move-related state variables."""
        self.move_state.reset()
    
    def reset_board(self):
        """Reset the chess board to starting position."""
        self.chess_board.reset()
    
    def set_board(self, board_obj: chess.Board):
        """
        Set the chess board state (primarily for testing).
        
        Args:
            board_obj: Chess board object to set
        """
        self.chess_board = board_obj


# Global instance for backward compatibility
_game_manager_instance: Optional[GameManager] = None


def _get_instance() -> GameManager:
    """Get or create the global game manager instance."""
    global _game_manager_instance
    if _game_manager_instance is None:
        _game_manager_instance = GameManager()
    return _game_manager_instance


# Backward compatibility functions
def subscribeGame(eventCallback, moveCallback, keyCallback, takebackCallback=None):
    """Subscribe to the game manager (backward compatibility)."""
    manager = _get_instance()
    manager.subscribe_game(eventCallback, moveCallback, keyCallback, takebackCallback)


def unsubscribeGame():
    """Unsubscribe from the game manager (backward compatibility)."""
    manager = _get_instance()
    manager.unsubscribe_game()


def setGameInfo(event, site, round, white, black):
    """Set game info (backward compatibility)."""
    manager = _get_instance()
    manager.set_game_info(event, site, round, white, black)


def computerMove(mv, forced=True):
    """Set computer move (backward compatibility)."""
    manager = _get_instance()
    manager.computer_move(mv, forced)


def setClock(white, black):
    """Set clock (backward compatibility)."""
    manager = _get_instance()
    manager.set_clock(white, black)


def startClock():
    """Start clock (backward compatibility)."""
    manager = _get_instance()
    manager.start_clock()


def resignGame(sideresigning):
    """Resign game (backward compatibility)."""
    manager = _get_instance()
    manager.resign_game(sideresigning)


def drawGame():
    """Draw game (backward compatibility)."""
    manager = _get_instance()
    manager.draw_game()


def getResult():
    """Get result (backward compatibility)."""
    manager = _get_instance()
    return manager.get_result()


def getBoard():
    """Get board (backward compatibility)."""
    manager = _get_instance()
    return manager.get_board()


def getFEN():
    """Get FEN (backward compatibility)."""
    manager = _get_instance()
    return manager.get_fen()


def resetMoveState():
    """Reset move state (backward compatibility)."""
    manager = _get_instance()
    manager.reset_move_state()


def resetBoard():
    """Reset board (backward compatibility)."""
    manager = _get_instance()
    manager.reset_board()


def setBoard(board_obj):
    """Set board (backward compatibility)."""
    manager = _get_instance()
    manager.set_board(board_obj)


# Export constants for backward compatibility
EVENT_NEW_GAME = GameEvent.NEW_GAME
EVENT_BLACK_TURN = GameEvent.BLACK_TURN
EVENT_WHITE_TURN = GameEvent.WHITE_TURN
EVENT_REQUEST_DRAW = GameEvent.REQUEST_DRAW
EVENT_RESIGN_GAME = GameEvent.RESIGN_GAME

