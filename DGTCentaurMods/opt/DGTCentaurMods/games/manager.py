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
        """Append the current board state to history."""
        current_state = board.getChessState()
        self.board_state_history.append(current_state)
        log.info(f"[GameManager._collect_board_state] Collected board state, history size: {len(self.board_state_history)}")
    
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
        # Only update database if game has been properly initialized
        # This prevents database operations with invalid game ID (game_db_id = -1) before _reset_game() is called
        if self.database_session is not None and self.game_db_id >= 0:
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
                log.warning(f"[GameManager.{context}] Game with id {self.game_db_id} not found in database. Result: {result_string}, termination: {termination}")
                # Cache the result even if not found in database
                self.cached_result = result_string
        elif self.database_session is not None and self.game_db_id < 0:
            log.warning(f"[GameManager.{context}] Skipping database update: game not initialized (game_db_id={self.game_db_id}). Result: {result_string}, termination: {termination}")
            # Cache the result even if database update is skipped
            self.cached_result = result_string
        else:
            # No database session, just cache the result
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
            self.is_showing_promotion = True
            widgets.promotion_options(PROMOTION_DISPLAY_LINE)
            promotion_choice = self._wait_for_promotion_choice()
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
        """Check if a takeback is in progress by comparing board states."""
        if self.takeback_callback is None or len(self.board_state_history) < 2:
            return False
        
        current_state = board.getChessState()
        previous_state = self.board_state_history[-2]
        
        if self._validate_board_state(current_state, previous_state):
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
            
            self.chess_board.pop()
            paths.write_fen_log(self.chess_board.fen())
            board.beep(board.SOUND_GENERAL)
            
            if self.takeback_callback is not None:
                self.takeback_callback()
            
            # Verify board is correct after takeback
            # Use logical chess board state (FEN) as expected state for consistency with correction mode
            time.sleep(0.2)
            current = board.getChessState()
            expected_state = self._chess_board_to_state(self.chess_board)
            
            if expected_state is not None and not self._validate_board_state(current, expected_state):
                log.info("[GameManager._check_takeback] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
                # Provide correction guidance using logical state
                self._provide_correction_guidance(current, expected_state)
            
            return True
        return False
    
    def _enter_correction_mode(self):
        """Enter correction mode to guide user in fixing board state.
        
        Uses logical chess board state (FEN) as expected state for consistency with
        the chess board widget display and correction guidance.
        """
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
            expected_state = self._chess_board_to_state(self.chess_board)
            
            if current_state is not None and expected_state is not None:
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
                expected_state = self._chess_board_to_state(self.chess_board)
                
                if expected_state is not None:
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
        """Execute a move from source to target square.
        
        Prevents moves from being executed after the game has ended.
        If the game is already over, logs a warning and returns early.
        """
        # Check if game is already over before executing move
        # This prevents moves from being executed after game termination, which would corrupt game state
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is not None:
            log.warning(f"[GameManager._execute_move] Attempted to execute move after game ended. Result: {self.chess_board.result()}, Termination: {outcome.termination}")
            board.beep(board.SOUND_WRONG_MOVE)
            board.ledsOff()
            self.move_state.reset()
            return
        
        from_name = chess.square_name(self.move_state.source_square)
        to_name = chess.square_name(target_square)
        piece_name = str(self.chess_board.piece_at(self.move_state.source_square))
        promotion_suffix = self._handle_promotion(target_square, piece_name, self.move_state.is_forced_move)
        
        if self.move_state.is_forced_move:
            move_uci = self.move_state.computer_move_uci
        else:
            move_uci = from_name + to_name + promotion_suffix
        
        # Make the move and update database
        # Catch exceptions from invalid UCI strings or illegal moves
        # This prevents the game thread from crashing on malformed move data
        try:
            move = chess.Move.from_uci(move_uci)
            self.chess_board.push(move)
        except ValueError as e:
            log.error(f"[GameManager._execute_move] Invalid move UCI or illegal move: {move_uci}. Error: {e}")
            board.beep(board.SOUND_WRONG_MOVE)
            board.ledsOff()
            self.move_state.reset()
            return
        
        paths.write_fen_log(self.chess_board.fen())
        
        # Only write to database if game has been properly initialized
        # This prevents writes with invalid game ID (game_db_id = -1) before _reset_game() is called
        if self.database_session is not None and self.game_db_id >= 0:
            game_move = models.GameMove(
                gameid=self.game_db_id,
                move=move_uci,
                fen=str(self.chess_board.fen())
            )
            self.database_session.add(game_move)
            self.database_session.commit()
        elif self.database_session is not None and self.game_db_id < 0:
            log.warning(f"[GameManager._execute_move] Skipping database write: game not initialized (game_db_id={self.game_db_id}). Move: {move_uci}")
        
        self._collect_board_state()
        self.move_state.reset()
        board.ledsOff()
        
        if self.move_callback is not None:
            self.move_callback(move_uci)
        
        board.beep(board.SOUND_GENERAL)
        board.led(target_square)
        
        # Check game outcome
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is None:
            self._switch_turn_with_event()
        else:
            board.beep(board.SOUND_GENERAL)
            result_string = str(self.chess_board.result())
            termination = str(outcome.termination)
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
                
                # Get the game ID - only set if query returns a valid result
                # This prevents setting game_db_id to None if the query fails
                self.game_db_id = -1
                game_id = self.database_session.query(func.max(models.Game.id)).scalar()
                if game_id is not None:
                    self.game_db_id = game_id
                    log.info(f"[GameManager._reset_game] Game initialized in database with id={self.game_db_id}, source={self.source_file}, event={self.game_info['event']}, white={self.game_info['white']}, black={self.game_info['black']}")
                    
                    # Create initial game move entry
                    game_move = models.GameMove(
                        gameid=self.game_db_id,
                        move='',
                        fen=str(self.chess_board.fen())
                    )
                    self.database_session.add(game_move)
                    self.database_session.commit()
                else:
                    log.error(f"[GameManager._reset_game] Failed to retrieve game ID from database. Game may not have been inserted correctly.")
                    # Keep game_db_id as -1 to prevent invalid database writes
            
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
            while not self.should_stop:
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
            return self.chess_board.turn
        
        def is_starting_position():
            current_state = board.getChessState()
            return self._is_starting_position(current_state)
        
        def is_showing_promotion():
            return self.is_showing_promotion
        
        self.clock_manager.start(get_current_turn, is_starting_position, is_showing_promotion)
    
    def computer_move(self, uci_move: str, forced: bool = True):
        """Set the computer move that the player is expected to make."""
        if not self.move_state.set_computer_move(uci_move, forced):
            return
        
        # Light up LEDs to indicate the move
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
        return self.chess_board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
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

