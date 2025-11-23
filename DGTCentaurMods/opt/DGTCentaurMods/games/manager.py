# This script manages a chess game, passing events and moves back to the calling script with callbacks
# The calling script is expected to manage the display using the centralized epaper service.
# Calling script initialises with subscribeGame(eventCallback, moveCallback, keyCallback)
# eventCallback feeds back events such as start of game, gameover
# moveCallback feeds back the chess moves made on the board
# keyCallback feeds back key presses from keys under the display

# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

from DGTCentaurMods.board import board
from DGTCentaurMods.display.epaper_service import service, widgets
from DGTCentaurMods.db import models
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func, select, create_engine
from scipy.optimize import linear_sum_assignment
import threading
import time
import chess
import sys
import inspect
import numpy as np
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log, logging


# Event constants
EVENT_NEW_GAME = 1
EVENT_BLACK_TURN = 2
EVENT_WHITE_TURN = 3
EVENT_REQUEST_DRAW = 4
EVENT_RESIGN_GAME = 5

# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
INVALID_SQUARE = -1

# Clock constants
SECONDS_PER_MINUTE = 60
CLOCK_DECREMENT_SECONDS = 2
CLOCK_DISPLAY_LINE = 13
PROMOTION_DISPLAY_LINE = 13

# Move constants
MIN_UCI_MOVE_LENGTH = 4

# Game constants
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# Starting position: pieces on ranks 1, 2, 7, 8 (squares 0-15 and 48-63)
STARTING_POSITION_STATE = bytearray(
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 1 (squares 0-7)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 2 (squares 8-15)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 3 (squares 16-23)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 4 (squares 24-31)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 5 (squares 32-39)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 6 (squares 40-47)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 7 (squares 48-55)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 8 (squares 56-63)
)


class ClockManager:
    """Manages chess clock timing and display."""
    
    def __init__(self, display_line: int = CLOCK_DISPLAY_LINE):
        self.white_time_seconds = 0
        self.black_time_seconds = 0
        self.display_line = display_line
        self.is_running = False
        self.clock_thread = None
        self.should_stop = False
    
    def set_times(self, white_seconds: int, black_seconds: int):
        """Set the clock times for both players."""
        self.white_time_seconds = white_seconds
        self.black_time_seconds = black_seconds
    
    def format_time(self, white_seconds: int, black_seconds: int) -> str:
        """Format time display string for clock."""
        white_minutes = white_seconds // SECONDS_PER_MINUTE
        white_secs = white_seconds % SECONDS_PER_MINUTE
        black_minutes = black_seconds // SECONDS_PER_MINUTE
        black_secs = black_seconds % SECONDS_PER_MINUTE
        return f"{white_minutes:02d}:{white_secs:02d}       {black_minutes:02d}:{black_secs:02d}"
    
    def _update_clock(self, current_turn: bool, is_starting_position: bool, showing_promotion: bool):
        """Update clock times based on current turn."""
        if current_turn == chess.WHITE and not is_starting_position:
            if self.white_time_seconds > 0:
                self.white_time_seconds = max(0, self.white_time_seconds - CLOCK_DECREMENT_SECONDS)
        elif current_turn == chess.BLACK:
            if self.black_time_seconds > 0:
                self.black_time_seconds = max(0, self.black_time_seconds - CLOCK_DECREMENT_SECONDS)
        
        if not showing_promotion:
            time_string = self.format_time(self.white_time_seconds, self.black_time_seconds)
            widgets.write_text(self.display_line, time_string)
    
    def start(self, current_turn_getter, is_starting_position_getter, showing_promotion_getter):
        """Start the clock thread."""
        if self.is_running:
            return
        
        self.should_stop = False
        self.is_running = True
        
        def clock_thread():
            while not self.should_stop:
                time.sleep(CLOCK_DECREMENT_SECONDS)
                current_turn = current_turn_getter()
                is_starting = is_starting_position_getter()
                showing_promo = showing_promotion_getter()
                self._update_clock(current_turn, is_starting, showing_promo)
        
        self.clock_thread = threading.Thread(target=clock_thread, daemon=True)
        self.clock_thread.start()
        
        # Initial display
        time_string = self.format_time(self.white_time_seconds, self.black_time_seconds)
        widgets.write_text(self.display_line, time_string)
    
    def stop(self):
        """Stop the clock thread."""
        self.should_stop = True
        self.is_running = False


class MoveState:
    """Tracks the state of a move in progress."""
    
    def __init__(self):
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_destination_squares = []
        self.computer_move_uci = ""
        self.is_forced_move = False
        self.source_piece_color = None  # Store piece color when lifted (for captures)
    
    def reset(self):
        """Reset all move state variables."""
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_destination_squares = []
        self.computer_move_uci = ""
        self.is_forced_move = False
        self.source_piece_color = None
    
    def set_computer_move(self, uci_move: str, forced: bool = True):
        """Set the computer move that the player is expected to make."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return False
        self.computer_move_uci = uci_move
        self.is_forced_move = forced
        return True


class CorrectionMode:
    """Manages correction mode for fixing misplaced pieces."""
    
    def __init__(self):
        self.is_active = False
        self.expected_state = None
        self.just_exited = False
    
    def enter(self, expected_state):
        """Enter correction mode."""
        self.is_active = True
        self.expected_state = expected_state
        self.just_exited = False
    
    def exit(self):
        """Exit correction mode."""
        self.is_active = False
        self.expected_state = None
        self.just_exited = True
    
    def clear_exit_flag(self):
        """Clear the just-exited flag."""
        self.just_exited = False


class GameManager:
    """Manages chess game state, moves, and board interactions."""
    
    def __init__(self):
        self.chess_board = chess.Board()
        self.board_state_history = []
        self.clock_manager = ClockManager()
        self.move_state = MoveState()
        self.correction_mode = CorrectionMode()
        
        # Callbacks
        self.event_callback = None
        self.move_callback = None
        self.key_callback = None
        self.takeback_callback = None
        
        # Game metadata
        self.game_info = {
            'event': '',
            'site': '',
            'round': '',
            'white': '',
            'black': ''
        }
        self.source_file = ""
        self.game_db_id = -1
        self.database_session = None
        self.database_engine = None  # Engine created in game thread
        self.cached_result = None  # Cache game result for thread-safe access
        
        # UI state
        self.is_showing_promotion = False
        self.is_in_menu = False
        
        # Thread control
        self.should_stop = False
        self.game_thread = None
        self._lock = threading.Lock()  # Lock for thread-safe access to shared state
    
    def _is_starting_position(self, board_state) -> bool:
        """Check if the board is in the starting position."""
        if board_state is None or len(board_state) != BOARD_SIZE:
            return False
        return bytearray(board_state) == STARTING_POSITION_STATE
    
    def _chess_board_to_state(self, chess_board: chess.Board) -> bytearray:
        """Convert chess board object to board state bytearray.
        
        Args:
            chess_board: The chess.Board object representing the logical game state
            
        Returns:
            bytearray: Board state where 1 indicates a piece is present, 0 indicates empty
            
        Raises:
            ValueError: If chess_board is None or invalid
        """
        if chess_board is None:
            raise ValueError("chess_board cannot be None")
        
        state = bytearray(BOARD_SIZE)
        try:
            for square in range(BOARD_SIZE):
                piece = chess_board.piece_at(square)
                state[square] = 1 if piece is not None else 0
        except Exception as e:
            log.error(f"[GameManager._chess_board_to_state] Error converting chess board to state: {e}")
            raise ValueError(f"Failed to convert chess board to state: {e}") from e
        
        return state
    
    def _collect_board_state(self):
        """Append the current board state to history.
        
        The logical chess board (self.chess_board) is the source of truth. This method:
        1. Always derives state from the logical chess board (authority)
        2. Optionally reads physical board state for validation/comparison
        3. Stores the logical state in history
        
        This ensures:
        - History always reflects the logical game state (source of truth)
        - Physical board errors don't corrupt the logical state
        - Takeback detection works correctly (requires history[-2])
        - Correction mode can detect when physical board doesn't match logical board
        """
        try:
            # Always use logical chess board as the source of truth
            logical_state = self._chess_board_to_state(self.chess_board)
            
            # Optionally validate against physical board (for discrepancy detection)
            # But don't let physical board errors affect the logical state
            physical_state = board.getChessState()
            if physical_state is not None and len(physical_state) == BOARD_SIZE:
                # Compare physical vs logical for discrepancy detection
                if not self._validate_board_state(physical_state, logical_state):
                    log.warning("[GameManager._collect_board_state] Physical board state differs from logical board state. Logical board is authoritative.")
                    # Log the discrepancy but continue with logical state
                    log.debug(f"[GameManager._collect_board_state] Logical FEN: {self.chess_board.fen()}")
            elif physical_state is None:
                log.debug("[GameManager._collect_board_state] Physical board state unavailable (communication timeout), using logical board state")
            else:
                log.warning(f"[GameManager._collect_board_state] Physical board state invalid (length {len(physical_state) if physical_state else 0}), using logical board state")
            
            # Store logical state in history (source of truth)
            self.board_state_history.append(logical_state)
            log.info(f"[GameManager._collect_board_state] Collected board state from logical chess board, history size: {len(self.board_state_history)}")
        except ValueError as e:
            log.error(f"[GameManager._collect_board_state] Failed to generate state from logical chess board: {e}")
            # This is a critical error - the logical board should always be valid
            # Don't append invalid state to history
            import traceback
            traceback.print_exc()
        except Exception as e:
            log.error(f"[GameManager._collect_board_state] Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            # Don't crash - the move was still executed in the chess board object
    
    def _validate_board_state(self, current_state, expected_state) -> bool:
        """Validate board state by comparing piece presence."""
        if current_state is None or expected_state is None:
            return False
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return False
        return bytearray(current_state) == bytearray(expected_state)
    
    def _uci_to_squares(self, uci_move: str):
        """Convert UCI move string to square indices."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return None, None
        from_square = ((ord(uci_move[1:2]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[0:1]) - ord("a"))
        to_square = ((ord(uci_move[3:4]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[2:3]) - ord("a"))
        return from_square, to_square
    
    def _calculate_legal_squares(self, source_square: int) -> list:
        """Calculate legal destination squares for a piece at the given square."""
        legal_destinations = [source_square]  # Include source square
        for move in self.chess_board.legal_moves:
            if move.from_square == source_square:
                legal_destinations.append(move.to_square)
        return legal_destinations
    
    def _switch_turn_with_event(self):
        """Trigger appropriate event callback based on current turn."""
        if self.event_callback is not None:
            if self.chess_board.turn == chess.WHITE:
                self.event_callback(EVENT_WHITE_TURN)
            else:
                self.event_callback(EVENT_BLACK_TURN)
    
    def _update_game_result(self, result_string: str, termination: str, context: str = ""):
        """Update game result in database and trigger event callback."""
        if self.database_session is not None:
            game_record = self.database_session.query(models.Game).filter(
                models.Game.id == self.game_db_id
            ).first()
            if game_record is not None:
                game_record.result = result_string
                self.database_session.flush()
                self.database_session.commit()
                self.cached_result = result_string  # Cache the result for thread-safe access
                log.info(f"[GameManager.{context}] Updated game result in database: id={self.game_db_id}, result={result_string}, termination={termination}")
            else:
                if self.game_db_id == -1:
                    log.warning(f"[GameManager.{context}] Game with id -1 not found in database (game was never initialized in database). Result: {result_string}, termination: {termination}")
                else:
                    log.warning(f"[GameManager.{context}] Game with id {self.game_db_id} not found in database. Result: {result_string}, termination: {termination}")
                # Cache the result even if not found in database
                self.cached_result = result_string
        
        if self.event_callback is not None:
            self.event_callback(termination)
    
    def _handle_promotion(self, target_square: int, piece_name: str, is_forced: bool) -> str:
        """Handle pawn promotion by prompting user for piece choice."""
        is_white_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
        is_black_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        if not is_forced:
            screen_backup = service.snapshot()
            with self._lock:
                self.is_showing_promotion = True
            widgets.promotion_options(PROMOTION_DISPLAY_LINE)
            promotion_choice = self._wait_for_promotion_choice()
            with self._lock:
                self.is_showing_promotion = False
            service.blit(screen_backup, 0, 0)
            return promotion_choice
        return ""
    
    def _wait_for_promotion_choice(self) -> str:
        """Wait for user to select promotion piece via button press."""
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
        """Check if a takeback is in progress by comparing physical board against logical board's previous state.
        
        The logical chess board is the authority. We detect takebacks when the physical board
        matches the logical board's state from two moves ago (before the last move).
        """
        if self.takeback_callback is None or len(self.board_state_history) < 2:
            return False
        
        # Check if chess board has moves to pop (history might be incomplete)
        if len(self.chess_board.move_stack) == 0:
            log.warning("[GameManager._check_takeback] Cannot takeback: no moves in chess board")
            return False
        
        # Get current physical board state
        current_physical_state = board.getChessState()
        if current_physical_state is None:
            log.debug("[GameManager._check_takeback] Physical board state unavailable, cannot detect takeback")
            return False
        
        # Get expected state from logical board history (source of truth)
        # history[-2] is the state before the last move (two moves ago)
        expected_logical_state = self.board_state_history[-2]
        
        # Validate that history state matches what we expect from chess board
        # If history is incomplete, we need to reconstruct the expected state from chess board
        try:
            # Create a temporary board to get the state before the last move
            temp_board = chess.Board(self.chess_board.fen())
            if len(temp_board.move_stack) > 0:
                temp_board.pop()
                expected_from_board = self._chess_board_to_state(temp_board)
                # Verify history matches chess board state
                if not self._validate_board_state(expected_logical_state, expected_from_board):
                    log.warning("[GameManager._check_takeback] History state does not match chess board state - history may be incomplete")
                    # Use chess board state as authoritative
                    expected_logical_state = expected_from_board
        except Exception as e:
            log.error(f"[GameManager._check_takeback] Failed to validate history state: {e}")
            # Continue with history state, but log the issue
        
        # Compare physical board against logical board's previous state
        if self._validate_board_state(current_physical_state, expected_logical_state):
            log.info("[GameManager._check_takeback] Takeback detected")
            board.ledsOff()
            self.board_state_history = self.board_state_history[:-1]
            
            # Remove last move from database
            if self.database_session is not None:
                last_move = self.database_session.query(models.GameMove).order_by(
                    models.GameMove.id.desc()
                ).first()
                if last_move is not None:
                    self.database_session.delete(last_move)
                    self.database_session.commit()
            
            # Pop move from chess board (should succeed since we checked move_stack length)
            try:
                self.chess_board.pop()
            except IndexError:
                log.error("[GameManager._check_takeback] Failed to pop move from chess board - no moves available")
                return False
            
            paths.write_fen_log(self.chess_board.fen())
            board.beep(board.SOUND_GENERAL)
            
            if self.takeback_callback is not None:
                self.takeback_callback()
            
            # Verify physical board matches logical board after takeback
            # Logical chess board is the authority - physical board must conform
            time.sleep(0.2)
            current_physical = board.getChessState()
            # If logical board state conversion fails, we cannot reliably continue
            expected_logical_state = self._chess_board_to_state(self.chess_board)
            
            if current_physical is not None:
                if not self._validate_board_state(current_physical, expected_logical_state):
                    log.info("[GameManager._check_takeback] Physical board does not match logical board after takeback, entering correction mode")
                    self._enter_correction_mode()
                    # Provide correction guidance: physical board should conform to logical board
                    self._provide_correction_guidance(current_physical, expected_logical_state)
            
            return True
        return False
    
    def _enter_correction_mode(self):
        """Enter correction mode to guide user in fixing board state.
        
        Uses logical chess board state (FEN) as expected state for consistency with
        the chess board widget display and correction guidance.
        
        Raises:
            ValueError: If logical board state conversion fails - cannot reliably continue
        """
        # If logical board state conversion fails, we cannot reliably continue
        expected_state = self._chess_board_to_state(self.chess_board)
        
        self.correction_mode.enter(expected_state)
        log.warning(f"[GameManager._enter_correction_mode] Entered correction mode")
    
    def _exit_correction_mode(self):
        """Exit correction mode and resume normal game flow."""
        self.correction_mode.exit()
        log.warning("[GameManager._exit_correction_mode] Exited correction mode")
        
        # Turn off correction LEDs first
        board.ledsOff()
        
        # Reset move state variables
        self.move_state.source_square = INVALID_SQUARE
        self.move_state.legal_destination_squares = []
        self.move_state.opponent_source_square = INVALID_SQUARE
        
        # Restore forced move LEDs if needed
        if self.move_state.is_forced_move and self.move_state.computer_move_uci:
            if len(self.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH:
                from_sq, to_sq = self._uci_to_squares(self.move_state.computer_move_uci)
                if from_sq is not None and to_sq is not None:
                    board.ledFromTo(from_sq, to_sq)
                    log.info(f"[GameManager._exit_correction_mode] Restored forced move LEDs: {self.move_state.computer_move_uci}")
    
    def _reconcile_state_after_checksum_failure(self):
        """Reconcile state after a checksum mismatch causes a lost board state response.
        
        When a checksum mismatch occurs, the board state response is lost. This method:
        1. If a player move was in progress, resets to the last known good state (before the move started)
        2. If a forced move was in play, ensures the physical board matches the logical board
        3. Enters correction mode to guide the user to fix any discrepancies
        
        The logical chess board (self.chess_board) is the authority - the physical board must conform.
        """
        log.warning("[GameManager._reconcile_state_after_checksum_failure] Checksum failure detected, reconciling state")
        
        # Check if a player move was in progress (piece lifted but not yet placed)
        move_in_progress = self.move_state.source_square >= 0
        
        if move_in_progress:
            # A player move was in progress - we lost the physical state, so we need to reset
            # to the last known good state (before the move started)
            log.warning("[GameManager._reconcile_state_after_checksum_failure] Player move in progress, resetting to last known good state")
            
            # Reset move state - this cancels the move in progress
            self.move_state.reset()
            board.ledsOff()
            
            # The logical board state is still correct (no move was executed)
            # We just need to ensure the physical board matches it
            # Get expected state from logical board
            # If logical board state conversion fails, we cannot reliably continue
            expected_state = self._chess_board_to_state(self.chess_board)
            
            # Enter correction mode to guide user to fix physical board
            self._enter_correction_mode()
            # Get current physical state and provide guidance
            time.sleep(0.2)  # Brief delay to allow board to stabilize
            current_physical = board.getChessState()
            if current_physical is not None:
                self._provide_correction_guidance(current_physical, expected_state)
            else:
                log.warning("[GameManager._reconcile_state_after_checksum_failure] Could not get current physical state for correction guidance")
        
        elif self.move_state.is_forced_move:
            # A forced move was in play - ensure physical board matches logical board
            log.warning("[GameManager._reconcile_state_after_checksum_failure] Forced move in play, ensuring physical board matches logical board")
            
            # Get expected state from logical board
            # If logical board state conversion fails, we cannot reliably continue
            expected_state = self._chess_board_to_state(self.chess_board)
            
            # Restore forced move LEDs
            if self.move_state.computer_move_uci and len(self.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH:
                from_sq, to_sq = self._uci_to_squares(self.move_state.computer_move_uci)
                if from_sq is not None and to_sq is not None:
                    board.ledFromTo(from_sq, to_sq)
                    log.info(f"[GameManager._reconcile_state_after_checksum_failure] Restored forced move LEDs: {self.move_state.computer_move_uci}")
            
            # Check if physical board matches expected state
            time.sleep(0.2)  # Brief delay to allow board to stabilize
            current_physical = board.getChessState()
            if current_physical is not None:
                if not self._validate_board_state(current_physical, expected_state):
                    log.warning("[GameManager._reconcile_state_after_checksum_failure] Physical board does not match logical board, entering correction mode")
                    self._enter_correction_mode()
                    self._provide_correction_guidance(current_physical, expected_state)
            else:
                log.warning("[GameManager._reconcile_state_after_checksum_failure] Could not get current physical state for validation")
        
        else:
            # No move in progress - just ensure physical board matches logical board
            log.info("[GameManager._reconcile_state_after_checksum_failure] No move in progress, verifying physical board matches logical board")
            
            # If logical board state conversion fails, we cannot reliably continue
            expected_state = self._chess_board_to_state(self.chess_board)
            
            time.sleep(0.2)  # Brief delay to allow board to stabilize
            current_physical = board.getChessState()
            if current_physical is not None:
                if not self._validate_board_state(current_physical, expected_state):
                    log.warning("[GameManager._reconcile_state_after_checksum_failure] Physical board does not match logical board, entering correction mode")
                    self._enter_correction_mode()
                    self._provide_correction_guidance(current_physical, expected_state)
    
    def _provide_correction_guidance(self, current_state, expected_state):
        """Provide LED guidance to correct misplaced pieces using Hungarian algorithm."""
        if current_state is None or expected_state is None:
            return
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return
        
        def square_to_row_col(square_idx):
            """Convert square index to (row, col)."""
            return (square_idx // BOARD_WIDTH), (square_idx % BOARD_WIDTH)
        
        def manhattan_distance(sq1, sq2):
            """Calculate Manhattan distance between two squares."""
            r1, c1 = square_to_row_col(sq1)
            r2, c2 = square_to_row_col(sq2)
            return abs(r1 - r2) + abs(c1 - c2)
        
        # Find misplaced pieces
        missing_squares = []  # Squares that should have pieces but don't
        extra_squares = []    # Squares that have pieces but shouldn't
        
        for i in range(BOARD_SIZE):
            if expected_state[i] == 1 and current_state[i] == 0:
                missing_squares.append(i)
            elif expected_state[i] == 0 and current_state[i] == 1:
                extra_squares.append(i)
        
        if len(missing_squares) == 0 and len(extra_squares) == 0:
            board.ledsOff()
            return
        
        log.warning(f"[GameManager._provide_correction_guidance] Found {len(extra_squares)} wrong pieces, {len(missing_squares)} missing pieces")
        
        # Guide one piece at a time
        if len(extra_squares) > 0 and len(missing_squares) > 0:
            if len(extra_squares) == 1 and len(missing_squares) == 1:
                from_idx = extra_squares[0]
                to_idx = missing_squares[0]
            else:
                # Use Hungarian algorithm for optimal pairing
                n_extra = len(extra_squares)
                n_missing = len(missing_squares)
                costs = np.zeros((n_extra, n_missing))
                for i, extra_sq in enumerate(extra_squares):
                    for j, missing_sq in enumerate(missing_squares):
                        costs[i, j] = manhattan_distance(extra_sq, missing_sq)
                
                row_ind, col_ind = linear_sum_assignment(costs)
                from_idx = extra_squares[row_ind[0]]
                to_idx = missing_squares[col_ind[0]]
            
            board.ledsOff()
            board.ledFromTo(from_idx, to_idx, intensity=5)
            log.warning(f"[GameManager._provide_correction_guidance] Guiding piece from {chess.square_name(from_idx)} to {chess.square_name(to_idx)}")
        else:
            # Only pieces missing or only extra pieces
            if len(missing_squares) > 0:
                board.ledsOff()
                for idx in missing_squares:
                    board.led(idx, intensity=5)
                log.warning(f"[GameManager._provide_correction_guidance] Pieces missing at: {[chess.square_name(sq) for sq in missing_squares]}")
            elif len(extra_squares) > 0:
                board.ledsOff()
                # Use ledArray for continuous flashing
                board.ledArray(extra_squares, speed=10, intensity=5)
                log.warning(f"[GameManager._provide_correction_guidance] Extra pieces at: {[chess.square_name(sq) for sq in extra_squares]}")
    
    def _handle_field_event_in_correction_mode(self, piece_event: int, field: int, time_in_seconds: float):
        """Handle field events during correction mode."""
        current_state = board.getChessState()
        
        # Check if board is in starting position (new game detection)
        if current_state is not None and len(current_state) == BOARD_SIZE:
            if self._is_starting_position(current_state):
                log.info("[GameManager._handle_field_event_in_correction_mode] Starting position detected - exiting correction and starting new game")
                board.ledsOff()
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                self._reset_game()
                return
        
        expected_state = self.correction_mode.expected_state
        if self._validate_board_state(current_state, expected_state):
            log.info("[GameManager._handle_field_event_in_correction_mode] Board corrected, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            return
        
        # Still incorrect, update guidance
        self._provide_correction_guidance(current_state, expected_state)
    
    def _handle_piece_lift(self, field: int, piece_color):
        """Handle piece lift event."""
        is_current_player_piece = (self.chess_board.turn == chess.WHITE) == (piece_color == True)
        
        if field not in self.move_state.legal_destination_squares and \
           self.move_state.source_square < 0 and \
           is_current_player_piece:
            # Generate legal destination squares for this piece
            self.move_state.legal_destination_squares = self._calculate_legal_squares(field)
            self.move_state.source_square = field
            # Store piece color for use during PLACE event (important for captures)
            self.move_state.source_piece_color = piece_color
        
        # Track opposing side lifts
        if not is_current_player_piece:
            self.move_state.opponent_source_square = field
        
        # Handle forced moves
        if self.move_state.is_forced_move and is_current_player_piece:
            field_name = chess.square_name(field)
            if field_name != self.move_state.computer_move_uci[0:2]:
                # Wrong piece lifted for forced move
                self.move_state.legal_destination_squares = [field]
            else:
                # Correct piece, limit to target square
                target = self.move_state.computer_move_uci[2:4]
                target_square = chess.parse_square(target)
                self.move_state.legal_destination_squares = [target_square]
                # Store piece color for forced moves too
                self.move_state.source_piece_color = piece_color
    
    def _handle_piece_place(self, field: int, piece_color):
        """Handle piece place event."""
        is_current_player_piece = (self.chess_board.turn == chess.WHITE) == (piece_color == True)
        
        # Handle opponent piece placed back
        if not is_current_player_piece and \
           self.move_state.opponent_source_square >= 0 and \
           field == self.move_state.opponent_source_square:
            board.ledsOff()
            self.move_state.opponent_source_square = INVALID_SQUARE
            return
        
        # Ignore stale PLACE events without corresponding LIFT
        if self.move_state.source_square < 0 and self.move_state.opponent_source_square < 0:
            # First, check if this PLACE event created an invalid board state (extra piece)
            # This check should happen for ALL cases, not just non-forced moves
            # 
            # IMPORTANT: Use the logical chess board state (FEN) as the expected state, not the physical board state.
            # This ensures consistency with the chess board widget display and avoids false positives when
            # the physical board matches the logical state but board_state_history contains stale data.
            # 
            # Timing assumption: This check occurs immediately after a PLACE event, so chess_board should
            # reflect the current logical game state. The chess_board is updated synchronously in _execute_move()
            # before any subsequent events can occur, so there should be no race condition.
            current_state = board.getChessState()
            # If logical board state conversion fails, we cannot reliably continue
            expected_state = self._chess_board_to_state(self.chess_board)
            
            if current_state is not None:
                # Check if there are extra pieces (pieces on squares that shouldn't have them)
                extra_squares = []
                if len(current_state) == BOARD_SIZE and len(expected_state) == BOARD_SIZE:
                    for i in range(BOARD_SIZE):
                        if expected_state[i] == 0 and current_state[i] == 1:
                            extra_squares.append(i)
                    
                    # Debug logging for troubleshooting
                    if len(extra_squares) > 0:
                        log.debug(f"[GameManager._handle_piece_place] Current FEN: {self.chess_board.fen()}")
                        log.debug(f"[GameManager._handle_piece_place] Extra pieces detected: {[chess.square_name(sq) for sq in extra_squares]}")
                
                if len(extra_squares) > 0:
                    log.warning(f"[GameManager._handle_piece_place] PLACE event without LIFT created invalid board state with {len(extra_squares)} extra piece(s) at {[chess.square_name(sq) for sq in extra_squares]}, entering correction mode")
                    board.beep(board.SOUND_WRONG_MOVE)
                    self._enter_correction_mode()
                    self._provide_correction_guidance(current_state, expected_state)
                    return
            else:
                log.debug(f"[GameManager._handle_piece_place] Cannot check board state: current_state={current_state is not None}, expected_state={expected_state is not None}")
            
            if self.correction_mode.just_exited:
                # Check if this is the forced move source square
                if self.move_state.is_forced_move and self.move_state.computer_move_uci:
                    if len(self.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH:
                        forced_source = chess.parse_square(self.move_state.computer_move_uci[0:2])
                        if field != forced_source:
                            log.info(f"[GameManager._handle_piece_place] Ignoring stale PLACE event after correction exit for field {field}")
                            self.correction_mode.clear_exit_flag()
                            return
                else:
                    log.info(f"[GameManager._handle_piece_place] Ignoring stale PLACE event after correction exit for field {field}")
                    self.correction_mode.clear_exit_flag()
                    return
            
            # For forced moves, ignore stale PLACE events on source square
            if self.move_state.is_forced_move and self.move_state.computer_move_uci:
                if len(self.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH:
                    forced_source = chess.parse_square(self.move_state.computer_move_uci[0:2])
                    if field == forced_source:
                        log.info(f"[GameManager._handle_piece_place] Ignoring stale PLACE event for forced move source field {field}")
                        self.correction_mode.clear_exit_flag()
                        return
            
            if not self.move_state.is_forced_move:
                log.info(f"[GameManager._handle_piece_place] Ignoring stale PLACE event for field {field}")
                self.correction_mode.clear_exit_flag()
                return
        
        # Clear exit flag on valid LIFT (handled in lift handler)
        
        # Check for illegal placement
        if field not in self.move_state.legal_destination_squares:
            board.beep(board.SOUND_WRONG_MOVE)
            log.warning(f"[GameManager._handle_piece_place] Piece placed on illegal square {field}")
            is_takeback = self._check_takeback()
            if not is_takeback:
                self._enter_correction_mode()
                current_state = board.getChessState()
                # If logical board state conversion fails, we cannot reliably continue
                expected_state = self._chess_board_to_state(self.chess_board)
                self._provide_correction_guidance(current_state, expected_state)
            return
        
        # Legal placement
        if field == self.move_state.source_square:
            # Piece placed back on source square
            board.ledsOff()
            self.move_state.source_square = INVALID_SQUARE
            self.move_state.legal_destination_squares = []
            self.move_state.source_piece_color = None
        else:
            # Valid move
            self._execute_move(field)
    
    def _execute_move(self, target_square: int):
        """Execute a move from source to target square."""
        with self._lock:
            # Check if game is already over before executing move
            if self.chess_board.outcome(claim_draw=True) is not None:
                log.warning("[GameManager._execute_move] Attempted to execute move in finished game, ignoring")
                return
            
            from_name = chess.square_name(self.move_state.source_square)
            to_name = chess.square_name(target_square)
            piece = self.chess_board.piece_at(self.move_state.source_square)
            if piece is None:
                log.error(f"[GameManager._execute_move] No piece at source square {from_name} (index {self.move_state.source_square}) - move state may be corrupted")
                board.beep(board.SOUND_WRONG_MOVE)
                # Reset move state and enter correction mode
                self.move_state.reset()
                self._enter_correction_mode()
                current_state = board.getChessState()
                # If logical board state conversion fails, we cannot reliably continue
                expected_state = self._chess_board_to_state(self.chess_board)
                if current_state is not None:
                    self._provide_correction_guidance(current_state, expected_state)
                return
            piece_name = str(piece)
            is_forced = self.move_state.is_forced_move
        
        promotion_suffix = self._handle_promotion(target_square, piece_name, is_forced)
        
        with self._lock:
            if self.move_state.is_forced_move:
                move_uci = self.move_state.computer_move_uci
                
                # For forced moves, the UCI should already include promotion if it's a promotion move
                # Validate that forced move UCI includes promotion when needed
                is_white_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
                is_black_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
                is_promotion_move = is_white_promotion or is_black_promotion
                
                if is_promotion_move and len(move_uci) < 5:
                    # Promotion move but UCI doesn't include promotion piece (should be 5 chars: e7e8q)
                    log.error(f"[GameManager._execute_move] Forced promotion move {move_uci} missing promotion piece")
                    board.beep(board.SOUND_WRONG_MOVE)
                    self.move_state.reset()
                    return
                
                # Validate forced move is still legal (board state may have changed)
                try:
                    move = chess.Move.from_uci(move_uci)
                    if move not in self.chess_board.legal_moves:
                        log.error(f"[GameManager._execute_move] Forced move {move_uci} is no longer legal on current board")
                        board.beep(board.SOUND_WRONG_MOVE)
                        # Reset forced move state
                        self.move_state.reset()
                        # Enter correction mode to guide user
                        self._enter_correction_mode()
                        current_state = board.getChessState()
                        # If logical board state conversion fails, we cannot reliably continue
                        expected_state = self._chess_board_to_state(self.chess_board)
                        if current_state is not None:
                            self._provide_correction_guidance(current_state, expected_state)
                        return
                except ValueError as e:
                    log.error(f"[GameManager._execute_move] Invalid forced move UCI {move_uci}: {e}")
                    board.beep(board.SOUND_WRONG_MOVE)
                    self.move_state.reset()
                    return
            else:
                move_uci = from_name + to_name + promotion_suffix
            
            # Validate move is legal before attempting database write
            try:
                move = chess.Move.from_uci(move_uci)
                if move not in self.chess_board.legal_moves:
                    log.error(f"[GameManager._execute_move] Move {move_uci} is not legal on current board")
                    board.beep(board.SOUND_WRONG_MOVE)
                    # Enter correction mode to guide user
                    self._enter_correction_mode()
                    current_state = board.getChessState()
                    # If logical board state conversion fails, we cannot reliably continue
                    expected_state = self._chess_board_to_state(self.chess_board)
                    if current_state is not None:
                        self._provide_correction_guidance(current_state, expected_state)
                    return
            except ValueError as e:
                log.error(f"[GameManager._execute_move] Invalid move UCI {move_uci}: {e}")
                board.beep(board.SOUND_WRONG_MOVE)
                # Enter correction mode to guide user
                self._enter_correction_mode()
                current_state = board.getChessState()
                # If logical board state conversion fails, we cannot reliably continue
                expected_state = self._chess_board_to_state(self.chess_board)
                if current_state is not None:
                    self._provide_correction_guidance(current_state, expected_state)
                return
            
            # Calculate expected FEN after move (using temporary board copy)
            temp_board = chess.Board(self.chess_board.fen())
            temp_board.push(move)
            expected_fen = temp_board.fen()
            
            # Add to database first (but don't commit yet) - makes operations atomic
            game_move = None
            if self.database_session is not None and self.game_db_id != -1:
                try:
                    game_move = models.GameMove(
                        gameid=self.game_db_id,
                        move=move_uci,
                        fen=str(expected_fen)
                    )
                    self.database_session.add(game_move)
                    # Don't commit yet - wait for chess board push to succeed
                except Exception as e:
                    log.error(f"[GameManager._execute_move] Failed to add move to database: {e}")
                    # Continue anyway - database is secondary to board state
            
            # Now push to chess board - if this fails, we'll rollback database
            try:
                self.chess_board.push(move)
            except ValueError as e:
                log.error(f"[GameManager._execute_move] Failed to execute move {move_uci}: {e}")
                board.beep(board.SOUND_WRONG_MOVE)
                # Rollback database if we added the move
                if game_move is not None and self.database_session is not None:
                    try:
                        self.database_session.rollback()
                        log.info(f"[GameManager._execute_move] Rolled back database transaction due to chess board push failure")
                    except Exception as rollback_error:
                        log.error(f"[GameManager._execute_move] Failed to rollback database session: {rollback_error}")
                # Enter correction mode to guide user
                self._enter_correction_mode()
                current_state = board.getChessState()
                # If logical board state conversion fails, we cannot reliably continue
                expected_state = self._chess_board_to_state(self.chess_board)
                if current_state is not None:
                    self._provide_correction_guidance(current_state, expected_state)
                return
            
            # Chess board push succeeded - now commit database
            if game_move is not None and self.database_session is not None:
                try:
                    self.database_session.commit()
                except Exception as e:
                    log.error(f"[GameManager._execute_move] Failed to commit move to database: {e}")
                    log.warning(f"[GameManager._execute_move] Board state updated but database commit failed - move: {move_uci}")
                    # Rollback the session to clear the failed transaction
                    try:
                        self.database_session.rollback()
                    except Exception as rollback_error:
                        log.error(f"[GameManager._execute_move] Failed to rollback database session: {rollback_error}")
                    # Note: Chess board state is already updated and is the source of truth
        
        # Get FEN after successful move
        with self._lock:
            fen = self.chess_board.fen()
        
        paths.write_fen_log(fen)
        
        # Collect board state (may fail if board communication is down, but move is already executed)
        with self._lock:
            self._collect_board_state()
            self.move_state.reset()
        
        board.ledsOff()
        
        # Always call move callback to update display, even if board state collection failed
        # The chess board object has the correct state, so the display should reflect it
        if self.move_callback is not None:
            try:
                self.move_callback(move_uci)
            except Exception as e:
                log.error(f"[GameManager._execute_move] Error in move callback: {e}")
                import traceback
                traceback.print_exc()
        
        board.beep(board.SOUND_GENERAL)
        board.led(target_square)
        
        # Check game outcome
        with self._lock:
            outcome = self.chess_board.outcome(claim_draw=True)
            if outcome is None:
                self._switch_turn_with_event()
            else:
                result_string = str(self.chess_board.result())
                termination = str(outcome.termination)
        
        if outcome is not None:
            board.beep(board.SOUND_GENERAL)
            self._update_game_result(result_string, termination, "_execute_move")
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """Handle field events (piece lift/place)."""
        field_name = chess.square_name(field)
        
        # For LIFT events, get piece color from the field
        # For PLACE events, use stored source piece color (important for captures)
        # where the destination square may have the opponent's piece
        if piece_event == 0:  # LIFT event
            piece_color = self.chess_board.color_at(field)
        else:  # PLACE event
            if self.move_state.source_piece_color is not None:
                # Use stored piece color from when the piece was lifted
                piece_color = self.move_state.source_piece_color
            else:
                # Fallback to destination square if no stored color (shouldn't normally happen)
                piece_color = self.chess_board.color_at(field)
        
        log.info(f"[GameManager._field_callback] piece_event={piece_event} field={field} fieldname={field_name} "
                 f"color_at={'White' if piece_color else 'Black'} time_in_seconds={time_in_seconds}")
        
        # Handle correction mode
        if self.correction_mode.is_active:
            self._handle_field_event_in_correction_mode(piece_event, field, time_in_seconds)
            return
        
        # Check for starting position when piece is placed
        if piece_event == 1:  # PLACE event
            current_state = board.getChessState()
            if self._is_starting_position(current_state):
                log.info("[GameManager._field_callback] Starting position detected via piece placement")
                self._reset_game()
                return
        
        is_lift = (piece_event == 0)
        is_place = (piece_event == 1)
        
        if is_lift:
            self._handle_piece_lift(field, piece_color)
            self.correction_mode.clear_exit_flag()
        elif is_place:
            self._handle_piece_place(field, piece_color)
    
    def _key_callback(self, key_pressed):
        """Handle key press events."""
        if self.key_callback is not None:
            if self.is_in_menu == 0 and key_pressed != board.Key.HELP:
                self.key_callback(key_pressed)
            if self.is_in_menu == 0 and key_pressed == board.Key.HELP:
                self.is_in_menu = 1
                widgets.resign_draw_menu(14)
            if self.is_in_menu == 1 and key_pressed == board.Key.BACK:
                widgets.write_text(14, "                   ")
                self.is_in_menu = 0
            if self.is_in_menu == 1 and key_pressed == board.Key.UP:
                widgets.write_text(14, "                   ")
                if self.event_callback is not None:
                    self.event_callback(EVENT_REQUEST_DRAW)
                self.is_in_menu = 0
            if self.is_in_menu == 1 and key_pressed == board.Key.DOWN:
                widgets.write_text(14, "                   ")
                if self.event_callback is not None:
                    self.event_callback(EVENT_RESIGN_GAME)
                self.is_in_menu = 0
    
    def _reset_game(self):
        """Reset the game to starting position."""
        try:
            log.info("[GameManager._reset_game] Resetting game to starting position")
            
            # End current game if one exists and hasn't been ended yet
            with self._lock:
                # Check if game was already over
                outcome = self.chess_board.outcome(claim_draw=True)
                game_was_over = outcome is not None
                
                if self.game_db_id != -1 and self.database_session is not None:
                    game_record = self.database_session.query(models.Game).filter(
                        models.Game.id == self.game_db_id
                    ).first()
                    if game_record is not None and game_record.result is None:
                        # Game exists but has no result - mark appropriately
                        if game_was_over:
                            # Game was over but result wasn't recorded - record it now
                            result_string = str(self.chess_board.result())
                            termination = str(outcome.termination)
                            log.info(f"[GameManager._reset_game] Ending current game (id={self.game_db_id}) with result {result_string} due to reset")
                            game_record.result = result_string
                            self.database_session.flush()
                            self.database_session.commit()
                            self.cached_result = result_string
                            log.info(f"[GameManager._reset_game] Recorded game {self.game_db_id} result: {result_string}, termination: {termination}")
                        else:
                            # Game was in progress - mark as abandoned
                            log.info(f"[GameManager._reset_game] Ending current game (id={self.game_db_id}) as abandoned due to reset")
                            game_record.result = "*"  # "*" indicates game abandoned/incomplete
                            self.database_session.flush()
                            self.database_session.commit()
                            self.cached_result = "*"
                            log.info(f"[GameManager._reset_game] Marked game {self.game_db_id} as abandoned in database")
            
            self.move_state.reset()
            self.chess_board.reset()
            paths.write_fen_log(self.chess_board.fen())
            
            # Double beep for game start
            board.beep(board.SOUND_GENERAL)
            time.sleep(0.3)
            board.beep(board.SOUND_GENERAL)
            board.ledsOff()
            
            if self.event_callback is not None:
                self.event_callback(EVENT_NEW_GAME)
                self.event_callback(EVENT_WHITE_TURN)
            
            # Log new game in database
            if self.database_session is not None:
                game = models.Game(
                    source=self.source_file,
                    event=self.game_info['event'],
                    site=self.game_info['site'],
                    round=self.game_info['round'],
                    white=self.game_info['white'],
                    black=self.game_info['black']
                )
                self.database_session.add(game)
                self.database_session.commit()
                
                # Get the game ID
                game_id = self.database_session.query(func.max(models.Game.id)).scalar()
                if game_id is None:
                    log.error("[GameManager._reset_game] Failed to get game ID after creation - query returned None")
                    raise ValueError("Game ID query returned None after game creation")
                self.game_db_id = game_id
                log.info(f"[GameManager._reset_game] Game initialized in database with id={self.game_db_id}, source={self.source_file}, event={self.game_info['event']}, white={self.game_info['white']}, black={self.game_info['black']}")
                
                # Create initial game move entry
                if self.game_db_id != -1:
                    game_move = models.GameMove(
                        gameid=self.game_db_id,
                        move='',
                        fen=str(self.chess_board.fen())
                    )
                    self.database_session.add(game_move)
                    self.database_session.commit()
            
            self.board_state_history = []
            self._collect_board_state()
        except Exception as e:
            log.error(f"[GameManager._reset_game] Error resetting game: {e}")
            import traceback
            traceback.print_exc()
    
    def _game_thread(self, event_callback, move_callback, key_callback, takeback_callback):
        """Main game thread that handles events."""
        self.event_callback = event_callback
        self.move_callback = move_callback
        self.key_callback = key_callback
        self.takeback_callback = takeback_callback
        
        # Create database engine and session in this thread to ensure all SQL operations happen in the same thread
        # We create a new engine here instead of using models.engine because the global engine's
        # connection pool was created in a different thread (module import time)
        thread_id = threading.get_ident()
        database_uri = paths.get_database_uri()
        # Configure SQLite with check_same_thread=False to allow connections created in this thread
        # to be used throughout the thread's lifetime. This is safe because we create and use
        # the engine entirely within this thread.
        if database_uri.startswith('sqlite'):
            self.database_engine = create_engine(
                database_uri,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True  # Verify connections before using
            )
        else:
            self.database_engine = create_engine(database_uri, pool_pre_ping=True)
        Session = sessionmaker(bind=self.database_engine)
        self.database_session = Session()
        log.info(f"[GameManager._game_thread] Database engine and session created in thread {thread_id}")
        
        board.ledsOff()
        log.info("[GameManager._game_thread] Subscribing to events")
        
        # Register failure callback for checksum mismatches
        # This allows us to reconcile state when board state responses are lost
        try:
            from DGTCentaurMods.board import board as board_module
            if hasattr(board_module.controller, '_failure_callback'):
                board_module.controller._failure_callback = self._reconcile_state_after_checksum_failure
                log.info("[GameManager._game_thread] Registered checksum failure callback")
        except Exception as e:
            log.warning(f"[GameManager._game_thread] Could not register failure callback: {e}")
        
        try:
            board.subscribeEvents(self._key_callback, self._field_callback)
        except Exception as e:
            log.error(f"[GameManager._game_thread] Error subscribing to events: {e}")
            log.error(f"[GameManager._game_thread] Error: {sys.exc_info()[1]}")
            # Clean up session and engine before returning
            if self.database_session is not None:
                try:
                    self.database_session.close()
                    self.database_session = None
                except Exception:
                    self.database_session = None
            if self.database_engine is not None:
                try:
                    self.database_engine.dispose()
                    self.database_engine = None
                except Exception:
                    self.database_engine = None
            return
        
        try:
            while True:
                with self._lock:
                    if self.should_stop:
                        break
                time.sleep(0.1)
        finally:
            # Clean up database session and engine in the same thread they were created
            if self.database_session is not None:
                try:
                    log.info(f"[GameManager._game_thread] Closing database session in thread {thread_id}")
                    self.database_session.close()
                    self.database_session = None
                except Exception as e:
                    log.error(f"[GameManager._game_thread] Error closing database session: {e}")
                    self.database_session = None
            if self.database_engine is not None:
                try:
                    log.info(f"[GameManager._game_thread] Disposing database engine in thread {thread_id}")
                    self.database_engine.dispose()
                    self.database_engine = None
                except Exception as e:
                    log.error(f"[GameManager._game_thread] Error disposing database engine: {e}")
                    self.database_engine = None
    
    def set_game_info(self, event: str, site: str, round_str: str, white: str, black: str):
        """Set game metadata for PGN files."""
        self.game_info = {
            'event': event,
            'site': site,
            'round': round_str,
            'white': white,
            'black': black
        }
    
    def set_clock(self, white_seconds: int, black_seconds: int):
        """Set the clock times for both players."""
        self.clock_manager.set_times(white_seconds, black_seconds)
    
    def start_clock(self):
        """Start the clock thread."""
        def get_current_turn():
            with self._lock:
                return self.chess_board.turn
        
        def is_starting_position():
            current_state = board.getChessState()
            return self._is_starting_position(current_state)
        
        def is_showing_promotion():
            with self._lock:
                return self.is_showing_promotion
        
        self.clock_manager.start(get_current_turn, is_starting_position, is_showing_promotion)
    
    def computer_move(self, uci_move: str, forced: bool = True):
        """Set the computer move that the player is expected to make."""
        with self._lock:
            if not self.move_state.set_computer_move(uci_move, forced):
                return
        
        # Light up LEDs to indicate the move (outside lock to avoid blocking)
        from_sq, to_sq = self._uci_to_squares(uci_move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
    
    def resign_game(self, side_resigning: int):
        """Handle game resignation."""
        result_string = "0-1" if side_resigning == 1 else "1-0"
        self._update_game_result(result_string, "Termination.RESIGN", "resign_game")
    
    def draw_game(self):
        """Handle game draw."""
        self._update_game_result("1/2-1/2", "Termination.DRAW", "draw_game")
    
    def get_result(self) -> str:
        """Get the result of the last game."""
        current_thread_id = threading.get_ident()
        game_thread_id = self.game_thread.ident if self.game_thread is not None else None
        
        # Check if we're in the game thread
        if current_thread_id != game_thread_id:
            # Not in game thread - use cached result
            if self.cached_result is not None:
                log.debug(f"[GameManager.get_result] Called from different thread (current={current_thread_id}, game_thread={game_thread_id}), returning cached result: {self.cached_result}")
                return self.cached_result
            else:
                log.warning(f"[GameManager.get_result] Called from different thread (current={current_thread_id}, game_thread={game_thread_id}) and no cached result available")
                return "Unknown"
        
        # We're in the game thread - can safely access database
        if self.database_session is None:
            # Fall back to cached result if available
            if self.cached_result is not None:
                return self.cached_result
            return "Unknown"
        
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
            result = str(game_data.result)
            self.cached_result = result  # Update cache
            return result
        return "Unknown"
    
    def get_board(self):
        """Get the current chess board state."""
        with self._lock:
            # Return a copy to avoid external modification and thread safety issues
            # Create a new board from FEN to ensure thread safety
            return chess.Board(self.chess_board.fen())
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        with self._lock:
            return self.chess_board.fen()
    
    def subscribe_game(self, event_callback, move_callback, key_callback, takeback_callback=None):
        """Subscribe to the game manager."""
        self.board_state_history = []
        self._collect_board_state()
        
        self.source_file = inspect.getsourcefile(sys._getframe(1))
        thread_id = threading.get_ident()
        log.info(f"[GameManager.subscribe_game] GameManager initialized, source_file={self.source_file}, thread_id={thread_id}")
        
        self.should_stop = False
        self.game_thread = threading.Thread(
            target=self._game_thread,
            args=(event_callback, move_callback, key_callback, takeback_callback)
        )
        self.game_thread.daemon = True
        self.game_thread.start()
    
    def unsubscribe_game(self):
        """Stop the game manager."""
        with self._lock:
            self.should_stop = True
        board.ledsOff()
        self.clock_manager.stop()
        
        # Wait for game thread to finish (it will clean up the database session)
        if self.game_thread is not None:
            self.game_thread.join(timeout=1.0)
            if self.game_thread.is_alive():
                log.warning("[GameManager.unsubscribe_game] Game thread did not finish within timeout")


# Global instance for backward compatibility
_game_manager_instance = None


def subscribeGame(event_callback, move_callback, key_callback, takeback_callback=None):
    """Subscribe to the game manager (backward compatibility function)."""
    global _game_manager_instance
    _game_manager_instance = GameManager()
    _game_manager_instance.subscribe_game(event_callback, move_callback, key_callback, takeback_callback)


def unsubscribeGame():
    """Unsubscribe from the game manager (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.unsubscribe_game()
        _game_manager_instance = None


def setGameInfo(event, site, round_str, white, black):
    """Set game metadata (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.set_game_info(event, site, round_str, white, black)


def setClock(white, black):
    """Set clock times (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.set_clock(white, black)


def startClock():
    """Start the clock (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.start_clock()


def computerMove(mv, forced=True):
    """Set computer move (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.computer_move(mv, forced)


def resignGame(side_resigning):
    """Resign game (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.resign_game(side_resigning)


def drawGame():
    """Draw game (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.draw_game()


def getResult():
    """Get game result (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        return _game_manager_instance.get_result()
    return "Unknown"


def getBoard():
    """Get chess board (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        return _game_manager_instance.get_board()
    return None


def getFEN():
    """Get FEN string (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        return _game_manager_instance.get_fen()
    return STARTING_FEN


def resetMoveState():
    """Reset move state (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.move_state.reset()


def resetBoard():
    """Reset board (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.chess_board.reset()


def setBoard(board_obj):
    """Set board (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.chess_board = board_obj

